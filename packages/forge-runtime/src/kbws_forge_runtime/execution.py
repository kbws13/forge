from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from enum import StrEnum
from time import monotonic
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kbws_forge_runtime.errors import (
    RunBudgetExceededError,
    RunCancelledError,
    RunTimeoutError,
    RunUsageUnavailableError,
    ToolApprovalRequiredError,
    ToolNotAllowedError,
)

T = TypeVar("T")


class ToolDecision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


class ToolPolicy(BaseModel):
    """Run-level permissions and retry declarations for tools."""

    model_config = ConfigDict(frozen=True)

    allowed_tools: frozenset[str] | None = None
    denied_tools: frozenset[str] = Field(default_factory=frozenset)
    approval_required: frozenset[str] = Field(default_factory=frozenset)
    retryable_tools: frozenset[str] = Field(default_factory=frozenset)

    @model_validator(mode="after")
    def validate_tool_sets(self) -> ToolPolicy:
        if self.allowed_tools is not None:
            conflicts = self.allowed_tools & self.denied_tools
            if conflicts:
                names = ", ".join(sorted(conflicts))
                raise ValueError(f"tools cannot be both allowed and denied: {names}")
            unknown_approvals = self.approval_required - self.allowed_tools
            if unknown_approvals:
                names = ", ".join(sorted(unknown_approvals))
                raise ValueError(f"approval tools must also be allowed: {names}")
        approval_conflicts = self.approval_required & self.denied_tools
        if approval_conflicts:
            names = ", ".join(sorted(approval_conflicts))
            raise ValueError(f"tools cannot require approval and be denied: {names}")
        return self

    def decision(self, tool_name: str) -> ToolDecision:
        if tool_name in self.denied_tools:
            return ToolDecision.DENY
        if self.allowed_tools is not None and tool_name not in self.allowed_tools:
            return ToolDecision.DENY
        if tool_name in self.approval_required:
            return ToolDecision.REQUIRE_APPROVAL
        return ToolDecision.ALLOW


class RunPolicy(BaseModel):
    """Limits enforced for one agent run.

    Token and cost budgets require usage metadata from the model response. If a
    configured budget cannot be measured, the run fails closed.
    """

    model_config = ConfigDict(frozen=True)

    timeout_seconds: float | None = Field(default=None, gt=0)
    max_model_calls: int | None = Field(default=None, ge=1)
    max_tool_calls: int | None = Field(default=None, ge=1)
    max_total_tokens: int | None = Field(default=None, ge=1)
    max_cost_usd: float | None = Field(default=None, gt=0)
    max_concurrency: int | None = Field(default=None, ge=1)
    model_retries: int = Field(default=0, ge=0)
    tool_retries: int = Field(default=0, ge=0)
    retry_backoff_seconds: float = Field(default=0, ge=0)
    tool_policy: ToolPolicy = Field(default_factory=ToolPolicy)


class ModelUsage(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)


class ToolApprovalRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    agent_id: str
    user_id: str
    session_id: str
    tool_name: str
    tool_input: Any = None


ToolApprovalHandler = Callable[[ToolApprovalRequest], Awaitable[bool]]
UsageResolver = Callable[[Any], ModelUsage | None]


def default_usage_resolver(response: Any) -> ModelUsage | None:
    usage = getattr(response, "usage_metadata", None)
    if not isinstance(usage, dict):
        metadata = getattr(response, "response_metadata", None)
        if isinstance(metadata, dict):
            usage = metadata.get("token_usage") or metadata.get("usage")
            if not isinstance(usage, dict):
                usage = metadata
    if not isinstance(usage, dict):
        return None

    input_tokens = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
    total_tokens = int(usage.get("total_tokens") or input_tokens + output_tokens)
    raw_cost = usage.get("cost_usd", usage.get("cost"))
    cost_usd = float(raw_cost) if isinstance(raw_cost, int | float) else None
    if total_tokens == 0 and cost_usd is None:
        return None
    return ModelUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cost_usd=cost_usd,
    )


@dataclass(slots=True)
class RunContext:
    run_id: str
    agent_id: str
    user_id: str
    session_id: str
    policy: RunPolicy = field(default_factory=RunPolicy)
    approval_handler: ToolApprovalHandler | None = None
    usage_resolver: UsageResolver = default_usage_resolver
    _started_at: float = field(default_factory=monotonic, init=False)
    _cancel_event: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    _cancel_reason: str = field(default="run cancelled", init=False)
    _model_calls: int = field(default=0, init=False)
    _tool_calls: int = field(default=0, init=False)
    _input_tokens: int = field(default=0, init=False)
    _output_tokens: int = field(default=0, init=False)
    _total_tokens: int = field(default=0, init=False)
    _cost_usd: float = field(default=0, init=False)
    _has_cost: bool = field(default=False, init=False)
    _sequence: int = field(default=0, init=False)
    _semaphore: asyncio.Semaphore | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if self.policy.max_concurrency is not None:
            self._semaphore = asyncio.Semaphore(self.policy.max_concurrency)

    @property
    def model_calls(self) -> int:
        return self._model_calls

    @property
    def tool_calls(self) -> int:
        return self._tool_calls

    @property
    def usage(self) -> ModelUsage:
        return ModelUsage(
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
            total_tokens=self._total_tokens,
            cost_usd=self._cost_usd if self._has_cost else None,
        )

    @property
    def elapsed_ms(self) -> float:
        return (monotonic() - self._started_at) * 1000

    @property
    def remaining_seconds(self) -> float | None:
        timeout = self.policy.timeout_seconds
        if timeout is None:
            return None
        return max(0.0, timeout - (monotonic() - self._started_at))

    @property
    def cancelled(self) -> bool:
        return self._cancel_event.is_set()

    @property
    def cancel_reason(self) -> str:
        return self._cancel_reason

    def next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    def cancel(self, reason: str = "run cancelled") -> None:
        self._cancel_reason = reason
        self._cancel_event.set()

    def check_active(self) -> None:
        if self.cancelled:
            raise RunCancelledError(self._cancel_reason)
        if self.remaining_seconds == 0:
            raise RunTimeoutError("run deadline exceeded")

    def reserve_model_call(self) -> None:
        self.check_active()
        limit = self.policy.max_model_calls
        if limit is not None and self._model_calls >= limit:
            raise RunBudgetExceededError(f"model call budget exceeded: {limit}")
        self._model_calls += 1

    def reserve_tool_call(self) -> None:
        self.check_active()
        limit = self.policy.max_tool_calls
        if limit is not None and self._tool_calls >= limit:
            raise RunBudgetExceededError(f"tool call budget exceeded: {limit}")
        self._tool_calls += 1

    def record_model_usage(self, response: Any) -> None:
        usage = self.usage_resolver(response)
        if usage is None:
            if self.policy.max_total_tokens is not None or self.policy.max_cost_usd is not None:
                raise RunUsageUnavailableError(
                    "model response did not include usage required by the run policy"
                )
            return

        self._input_tokens += usage.input_tokens
        self._output_tokens += usage.output_tokens
        self._total_tokens += usage.total_tokens
        if usage.cost_usd is not None:
            self._cost_usd += usage.cost_usd
            self._has_cost = True

        token_limit = self.policy.max_total_tokens
        if token_limit is not None and self._total_tokens > token_limit:
            raise RunBudgetExceededError(f"token budget exceeded: {token_limit}")
        cost_limit = self.policy.max_cost_usd
        if cost_limit is not None:
            if usage.cost_usd is None:
                raise RunUsageUnavailableError(
                    "model response did not include cost required by the run policy"
                )
            if self._cost_usd > cost_limit:
                raise RunBudgetExceededError(f"cost budget exceeded: {cost_limit} USD")

    async def await_controlled(self, operation: Callable[[], Awaitable[T]]) -> T:
        self.check_active()
        operation_task = asyncio.ensure_future(operation())
        cancel_task = asyncio.create_task(self._cancel_event.wait())
        try:
            done, _ = await asyncio.wait(
                {operation_task, cancel_task},
                timeout=self.remaining_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if operation_task in done:
                cancel_task.cancel()
                with suppress(BaseException):
                    await cancel_task
                return await operation_task
            operation_task.cancel()
            with suppress(BaseException):
                await operation_task
            if cancel_task in done:
                raise RunCancelledError(self._cancel_reason)
            raise RunTimeoutError("run deadline exceeded")
        except BaseException:
            if not operation_task.done():
                operation_task.cancel()
            if not cancel_task.done():
                cancel_task.cancel()
            with suppress(BaseException):
                await operation_task
            with suppress(BaseException):
                await cancel_task
            raise

    @asynccontextmanager
    async def execution_slot(self):
        if self._semaphore is None:
            yield
            return
        await self.await_controlled(self._semaphore.acquire)
        try:
            yield
        finally:
            self._semaphore.release()

    async def backoff(self) -> None:
        if self.policy.retry_backoff_seconds:
            await self.await_controlled(lambda: asyncio.sleep(self.policy.retry_backoff_seconds))


_CONTROL_ERRORS = (
    RunBudgetExceededError,
    RunCancelledError,
    RunTimeoutError,
    RunUsageUnavailableError,
    ToolApprovalRequiredError,
    ToolNotAllowedError,
)


class ModelExecutor:
    def __init__(self, context: RunContext) -> None:
        self._context = context

    async def ainvoke(self, operation: Callable[[], Awaitable[T]]) -> T:
        retries = self._context.policy.model_retries
        for attempt in range(retries + 1):
            self._context.reserve_model_call()
            try:
                async with self._context.execution_slot():
                    response = await self._context.await_controlled(operation)
                self._context.record_model_usage(response)
                return response
            except _CONTROL_ERRORS:
                raise
            except Exception:
                if attempt >= retries:
                    raise
                await self._context.backoff()
        raise AssertionError("unreachable")


class ToolExecutor:
    def __init__(self, context: RunContext) -> None:
        self._context = context

    async def ainvoke(
        self,
        tool_name: str,
        tool_input: Any,
        operation: Callable[[], Awaitable[T]],
    ) -> T:
        tool_policy = self._context.policy.tool_policy
        decision = tool_policy.decision(tool_name)
        if decision is ToolDecision.DENY:
            raise ToolNotAllowedError(f"tool is not allowed by run policy: {tool_name}")
        if decision is ToolDecision.REQUIRE_APPROVAL:
            handler = self._context.approval_handler
            if handler is None:
                raise ToolApprovalRequiredError(f"tool requires approval: {tool_name}")
            request = ToolApprovalRequest(
                run_id=self._context.run_id,
                agent_id=self._context.agent_id,
                user_id=self._context.user_id,
                session_id=self._context.session_id,
                tool_name=tool_name,
                tool_input=tool_input,
            )
            approved = await self._context.await_controlled(lambda: handler(request))
            if not approved:
                raise ToolNotAllowedError(f"tool approval was denied: {tool_name}")

        retries = (
            self._context.policy.tool_retries if tool_name in tool_policy.retryable_tools else 0
        )
        for attempt in range(retries + 1):
            self._context.reserve_tool_call()
            try:
                async with self._context.execution_slot():
                    return await self._context.await_controlled(operation)
            except _CONTROL_ERRORS:
                raise
            except Exception:
                if attempt >= retries:
                    raise
                await self._context.backoff()
        raise AssertionError("unreachable")


_CURRENT_RUN_CONTEXT: ContextVar[RunContext | None] = ContextVar("forge_run_context", default=None)


def current_run_context() -> RunContext | None:
    return _CURRENT_RUN_CONTEXT.get()


def bind_run_context(context: RunContext) -> Token[RunContext | None]:
    return _CURRENT_RUN_CONTEXT.set(context)


def reset_run_context(token: Token[RunContext | None]) -> None:
    _CURRENT_RUN_CONTEXT.reset(token)


__all__ = [
    "ModelExecutor",
    "ModelUsage",
    "RunContext",
    "RunPolicy",
    "ToolApprovalHandler",
    "ToolApprovalRequest",
    "ToolExecutor",
    "ToolPolicy",
    "UsageResolver",
]
