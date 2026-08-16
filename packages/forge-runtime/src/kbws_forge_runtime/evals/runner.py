"""EvalRunner: execute a suite against the runtime, grade, and persist.

Live mode calls the agent for every case (bounded by the suite's RunPolicy:
per-run timeout/budget come from ``RunPolicy`` itself, cross-case concurrency
from ``RunPolicy.max_concurrency``). Replay mode re-grades recorded runs.
signalled explicitly rather than half-implemented.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
from collections.abc import Sequence
from datetime import UTC, datetime
from time import monotonic
from typing import Any, Literal

from kbws_forge_runtime.errors import ForgeRuntimeError
from kbws_forge_runtime.evals.models import (
    EvalCase,
    EvalCaseResult,
    EvalRun,
    EvalStatus,
    GraderCaseResult,
    GraderResult,
    worst_status,
)
from kbws_forge_runtime.evals.store import EvalStore
from kbws_forge_runtime.execution import ModelUsage
from kbws_forge_runtime.models import ChatMessage, ChatResult
from kbws_forge_runtime.runtime import AgentRuntime

Mode = Literal["live", "replay"]


def _iso() -> str:
    return datetime.now(UTC).isoformat()


def _git_sha() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _suite_fingerprint(suite) -> str:
    """Deterministic fingerprint of the suite definition (provenance)."""
    payload = {
        "suite_id": suite.id,
        "agent_id": suite.agent_id,
        "cases": [
            {"id": case.id, "expected": case.expected, "tags": list(case.tags)}
            for case in suite.cases
        ],
        "graders": [grader.key for grader in suite.graders],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]


def _chat_result_from_events(
    run_id: str, events: Sequence[dict[str, Any]]
) -> ChatResult | None:
    """Reconstruct a ChatResult from a recorded run's terminal event (replay)."""
    finished = next(
        (event for event in events if event.get("type") == "run_finished"), None
    )
    if finished is None:
        return None
    message = finished.get("message")
    usage = finished.get("usage") or {}
    return ChatResult(
        run_id=run_id,
        agent_id=finished.get("agent_id", ""),
        user_id="",
        session_id=finished.get("session_id", ""),
        message=ChatMessage(**message) if message else ChatMessage.assistant(""),
        parsed=finished.get("parsed"),
        duration_ms=finished.get("duration_ms"),
        model_calls=finished.get("model_calls", 0),
        tool_calls=finished.get("tool_calls", 0),
        usage=ModelUsage(**usage),
    )


class EvalRunner:
    """Executes :class:`EvalSuite` cases against an :class:`AgentRuntime`."""

    def __init__(self, runtime: AgentRuntime, store: EvalStore | None = None) -> None:
        self._runtime = runtime
        self._store = store or EvalStore()

    @property
    def store(self) -> EvalStore:
        return self._store

    async def run(
        self,
        suite,
        *,
        mode: Mode = "live",
        provenance: dict[str, Any] | None = None,
        case_ids: Sequence[str] | None = None,
        repetitions: int | None = None,
    ) -> EvalRun:
        """Execute a suite and persist the resulting :class:`EvalRun`.

        ``mode="live"`` calls the agent for every case; ``mode="replay"``
        re-grades previously recorded runs (zero external calls) using the
        run-id mapping in the EvalStore.
        """
        if mode == "replay":
            return await self._run_replay(suite, provenance, case_ids, repetitions)
        if mode != "live":
            raise ValueError(f"unknown eval mode: {mode!r}")

        effective_reps = repetitions if repetitions is not None else suite.repetitions
        eval_run = EvalRun(
            suite_id=suite.id,
            agent_id=suite.agent_id,
            repetitions=effective_reps,
            provenance=self._provenance(suite, provenance, mode="live"),
        )

        cases = [
            case for case in suite.cases if not case_ids or case.id in case_ids
        ]
        semaphore: asyncio.Semaphore | None = None
        if suite.policy is not None and suite.policy.max_concurrency:
            semaphore = asyncio.Semaphore(suite.policy.max_concurrency)

        results = await asyncio.gather(
            *(self._run_case(suite, case, semaphore, effective_reps) for case in cases),
            return_exceptions=True,
        )
        case_results: list[EvalCaseResult] = []
        for case, outcome in zip(cases, results, strict=True):
            if isinstance(outcome, EvalCaseResult):
                case_results.append(outcome)
            else:  # 基础设施异常：记为该 case 失败，不中断整个 suite
                case_results.append(
                    EvalCaseResult(
                        case_id=case.id,
                        status=EvalStatus.FAILED,
                        score=0.0,
                        failure_reasons=(f"runner error: {outcome}",),
                        error=str(outcome),
                    )
                )

        eval_run = EvalRun(
            eval_run_id=eval_run.eval_run_id,
            suite_id=suite.id,
            agent_id=suite.agent_id,
            status="finished",
            started_at=eval_run.started_at,
            completed_at=_iso(),
            repetitions=effective_reps,
            provenance=eval_run.provenance,
            cases=tuple(case_results),
        )
        await self._store.save(eval_run)
        return eval_run

    def _provenance(
        self, suite, extras: dict[str, Any] | None, *, mode: str
    ) -> dict[str, Any]:
        policy = suite.policy or getattr(self._runtime, "_default_policy", None)
        snapshot = policy.model_dump(mode="json") if policy else {}
        return {
            "policy": snapshot,
            "git_sha": _git_sha(),
            "repetitions": suite.repetitions,
            "suite_fingerprint": _suite_fingerprint(suite),
            "mode": mode,
            **(extras or {}),
        }

    # --- case execution ---

    async def _run_case(
        self,
        suite,
        case: EvalCase,
        semaphore: asyncio.Semaphore | None,
        repetitions: int,
    ) -> EvalCaseResult:
        started = monotonic()
        executions: list[tuple[ChatResult, list[dict[str, Any]]]] = []
        errors: list[str] = []
        all_run_ids: list[str] = []

        for _ in range(repetitions):
            try:
                if semaphore is not None:
                    async with semaphore:
                        run_ids, result = await self._execute_once(suite, case)
                else:
                    run_ids, result = await self._execute_once(suite, case)
            except ForgeRuntimeError as exc:
                errors.append(str(exc))
                continue
            all_run_ids.extend(run_ids)
            executions.append((result, self._events_for(run_ids)))

        if not executions:
            return EvalCaseResult(
                case_id=case.id,
                status=EvalStatus.FAILED,
                score=0.0,
                failure_reasons=tuple(errors) or ("all executions failed",),
                duration_ms=(monotonic() - started) * 1000,
                error="; ".join(errors),
            )
        return await self._grade_case(
            suite, case, executions, tuple(all_run_ids), started, errors
        )

    async def _grade_case(
        self,
        suite,
        case: EvalCase,
        executions: Sequence[tuple[ChatResult, list[dict[str, Any]]]],
        run_ids: tuple[str, ...],
        started: float,
        errors: Sequence[str] = (),
    ) -> EvalCaseResult:
        graders = case.graders or suite.graders
        if not graders:
            return EvalCaseResult(
                case_id=case.id,
                run_ids=run_ids,
                status=EvalStatus.NOT_EVALUATED,
                failure_reasons=("no graders configured",),
                duration_ms=(monotonic() - started) * 1000,
            )

        grader_results = [
            await self._grade_grader(grader, case, executions)
            for grader in graders
        ]
        failure_reasons = [
            result.reason
            for result in grader_results
            if result.status == EvalStatus.FAILED and result.reason
        ]
        failure_reasons.extend(errors)
        scored = [result.score for result in grader_results if result.score is not None]
        status = worst_status([result.status for result in grader_results])
        return EvalCaseResult(
            case_id=case.id,
            run_ids=run_ids,
            status=status,
            score=sum(scored) / len(scored) if scored else None,
            graders=tuple(grader_results),
            failure_reasons=tuple(failure_reasons),
            duration_ms=(monotonic() - started) * 1000,
        )

    async def _run_replay(
        self,
        suite,
        provenance: dict[str, Any] | None,
        case_ids: Sequence[str] | None,
        repetitions: int | None,
    ) -> EvalRun:
        """Re-grade previously recorded runs for each case (zero external calls).

        Recorded runs are found via the EvalStore's run-id mapping, and their
        events/terminal state are read from the runtime's TraceStore.
        """
        effective_reps = repetitions if repetitions is not None else suite.repetitions
        eval_run = EvalRun(
            suite_id=suite.id,
            agent_id=suite.agent_id,
            repetitions=effective_reps,
            provenance=self._provenance(suite, provenance, mode="replay"),
        )
        cases = [
            case for case in suite.cases if not case_ids or case.id in case_ids
        ]
        results = [await self._replay_case(suite, case) for case in cases]
        eval_run = EvalRun(
            eval_run_id=eval_run.eval_run_id,
            suite_id=suite.id,
            agent_id=suite.agent_id,
            status="finished",
            started_at=eval_run.started_at,
            completed_at=_iso(),
            repetitions=effective_reps,
            provenance=eval_run.provenance,
            cases=tuple(results),
        )
        await self._store.save(eval_run)
        return eval_run

    async def _replay_case(self, suite, case: EvalCase) -> EvalCaseResult:
        started = monotonic()
        run_ids = self._store.case_run_ids(suite.id, case.id)
        if not run_ids:
            return EvalCaseResult(
                case_id=case.id,
                status=EvalStatus.NOT_EVALUATED,
                failure_reasons=("no recorded run to replay",),
                duration_ms=(monotonic() - started) * 1000,
            )
        executions: list[tuple[ChatResult, list[dict[str, Any]]]] = []
        for run_id in run_ids:
            events = self._events_for([run_id])
            result = _chat_result_from_events(run_id, events)
            if result is not None:
                executions.append((result, events))
        if not executions:
            return EvalCaseResult(
                case_id=case.id,
                run_ids=run_ids,
                status=EvalStatus.NOT_EVALUATED,
                failure_reasons=("recorded run has no run_finished event",),
                duration_ms=(monotonic() - started) * 1000,
            )
        return await self._grade_case(suite, case, executions, run_ids, started)

    async def _execute_once(
        self, suite, case: EvalCase
    ) -> tuple[list[str], ChatResult]:
        """Run one case once; returns (run_ids, final ChatResult)."""
        if case.conversation:
            session = self._runtime.create_session(suite.agent_id, suite.user_id)
            run_ids: list[str] = []
            result: ChatResult | None = None
            for message in case.conversation:
                result = await self._runtime.chat(
                    suite.agent_id,
                    suite.user_id,
                    message,
                    session_id=session.session_id,
                    variables=case.variables,
                    policy=suite.policy,
                )
                run_ids.append(result.run_id)
            assert result is not None
            return run_ids, result
        result = await self._runtime.chat(
            suite.agent_id,
            suite.user_id,
            case.input or "",
            variables=case.variables,
            policy=suite.policy,
        )
        return [result.run_id], result

    def _events_for(self, run_ids: Sequence[str]) -> list[dict[str, Any]]:
        """Collect recorded trace events for the runs (TraceStore is always on)."""
        events: list[dict[str, Any]] = []
        for run_id in run_ids:
            record = self._runtime.trace_store.get_run(run_id)
            if record:
                events.extend(record.get("events", []))
        return events

    async def _grade_grader(
        self,
        grader,
        case: EvalCase,
        executions: Sequence[tuple[ChatResult, list[dict[str, Any]]]],
    ) -> GraderCaseResult:
        """Grade every repetition with one grader, then aggregate."""
        attempts: list[GraderResult] = []
        for result, events in executions:
            try:
                attempts.append(await grader.grade(case, result, events))
            except Exception as exc:  # grader 自身失败 → NOT_EVALUATED（ADK 隔离语义）
                attempts.append(
                    GraderResult(
                        key=grader.key,
                        status=EvalStatus.NOT_EVALUATED,
                        reason=f"grader {grader.key!r} raised: {exc}",
                    )
                )
        scored = [attempt.score for attempt in attempts if attempt.score is not None]
        failed = [attempt.reason for attempt in attempts if attempt.status == EvalStatus.FAILED]
        status = worst_status([attempt.status for attempt in attempts])
        reasons = "; ".join(reason for reason in failed if reason)
        if not reasons and status == EvalStatus.NOT_EVALUATED:
            reasons = "; ".join(
                attempt.reason for attempt in attempts if attempt.reason
            )
        return GraderCaseResult(
            key=grader.key,
            status=status,
            score=sum(scored) / len(scored) if scored else None,
            reason=reasons,
        )


__all__ = ["EvalRunner", "Mode"]
