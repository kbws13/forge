import asyncio
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from kbws_forge_runtime import (
    ModelExecutor,
    RunBudgetExceededError,
    RunCancelledError,
    RunContext,
    RunPolicy,
    RunTimeoutError,
    RunUsageUnavailableError,
    ToolApprovalRequest,
    ToolExecutor,
    ToolNotAllowedError,
    ToolPolicy,
)


def make_context(
    policy: RunPolicy | None = None,
    *,
    approval_handler=None,
) -> RunContext:
    return RunContext(
        run_id="run-1",
        agent_id="agent-1",
        user_id="user-1",
        session_id="session-1",
        policy=policy or RunPolicy(),
        approval_handler=approval_handler,
    )


def test_tool_policy_rejects_conflicting_declarations() -> None:
    with pytest.raises(ValidationError, match="both allowed and denied"):
        ToolPolicy(allowed_tools={"write"}, denied_tools={"write"})


async def test_model_executor_accounts_usage_and_enforces_call_budget() -> None:
    context = make_context(RunPolicy(max_model_calls=1, max_total_tokens=10))
    executor = ModelExecutor(context)

    result = await executor.ainvoke(
        lambda: asyncio.sleep(
            0,
            result=AIMessage(
                content="ok",
                usage_metadata={"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
            ),
        )
    )

    assert result.content == "ok"
    assert context.model_calls == 1
    assert context.usage.total_tokens == 3
    with pytest.raises(RunBudgetExceededError, match="model call budget"):
        await executor.ainvoke(lambda: asyncio.sleep(0, result=AIMessage(content="late")))


async def test_model_executor_fails_closed_when_budget_usage_is_missing() -> None:
    context = make_context(RunPolicy(max_total_tokens=10))

    with pytest.raises(RunUsageUnavailableError, match="did not include usage"):
        await ModelExecutor(context).ainvoke(
            lambda: asyncio.sleep(0, result=AIMessage(content="no usage"))
        )


async def test_cost_budget_requires_cost_on_every_model_response() -> None:
    context = make_context(RunPolicy(max_cost_usd=1.0))
    executor = ModelExecutor(context)

    await executor.ainvoke(
        lambda: asyncio.sleep(
            0,
            result=SimpleNamespace(
                usage_metadata={
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "total_tokens": 2,
                    "cost_usd": 0.1,
                }
            ),
        )
    )

    with pytest.raises(RunUsageUnavailableError, match="cost required"):
        await executor.ainvoke(
            lambda: asyncio.sleep(
                0,
                result=SimpleNamespace(
                    usage_metadata={
                        "input_tokens": 1,
                        "output_tokens": 1,
                        "total_tokens": 2,
                    }
                ),
            )
        )


async def test_model_executor_enforces_timeout_and_cancellation() -> None:
    timeout_context = make_context(RunPolicy(timeout_seconds=0.01))
    with pytest.raises(RunTimeoutError):
        await ModelExecutor(timeout_context).ainvoke(
            lambda: asyncio.sleep(1, result=AIMessage(content="late"))
        )

    cancel_context = make_context()
    started = asyncio.Event()

    async def wait_forever() -> AIMessage:
        started.set()
        await asyncio.sleep(60)
        return AIMessage(content="late")

    task = asyncio.create_task(ModelExecutor(cancel_context).ainvoke(wait_forever))
    await started.wait()
    cancel_context.cancel("stopped by caller")
    with pytest.raises(RunCancelledError, match="stopped by caller"):
        await task


async def test_tool_executor_enforces_policy_approval_and_safe_retries() -> None:
    denied_context = make_context(RunPolicy(tool_policy=ToolPolicy(denied_tools={"write"})))
    called = False

    async def forbidden_operation() -> str:
        nonlocal called
        called = True
        return "bad"

    with pytest.raises(ToolNotAllowedError, match="write"):
        await ToolExecutor(denied_context).ainvoke("write", {}, forbidden_operation)
    assert not called
    assert denied_context.tool_calls == 0

    approvals: list[ToolApprovalRequest] = []

    async def approve(request: ToolApprovalRequest) -> bool:
        approvals.append(request)
        return True

    retry_context = make_context(
        RunPolicy(
            max_tool_calls=2,
            tool_retries=1,
            tool_policy=ToolPolicy(
                allowed_tools={"read"},
                approval_required={"read"},
                retryable_tools={"read"},
            ),
        ),
        approval_handler=approve,
    )
    attempts = 0

    async def flaky_read() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("temporary")
        return "ok"

    result = await ToolExecutor(retry_context).ainvoke("read", {"path": "a"}, flaky_read)

    assert result == "ok"
    assert attempts == 2
    assert retry_context.tool_calls == 2
    assert [request.tool_name for request in approvals] == ["read"]
    assert approvals[0].user_id == "user-1"


async def test_execution_context_limits_concurrency() -> None:
    context = make_context(RunPolicy(max_concurrency=1))
    executor = ToolExecutor(context)
    active = 0
    highest_active = 0

    async def operation() -> str:
        nonlocal active, highest_active
        active += 1
        highest_active = max(highest_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return "ok"

    results = await asyncio.gather(
        executor.ainvoke("first", {}, operation),
        executor.ainvoke("second", {}, operation),
    )

    assert results == ["ok", "ok"]
    assert highest_active == 1
