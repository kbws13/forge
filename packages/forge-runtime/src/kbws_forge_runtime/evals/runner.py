"""EvalRunner: execute a suite against the runtime, grade, and persist.

Live mode calls the agent for every case (bounded by the suite's RunPolicy:
per-run timeout/budget come from ``RunPolicy`` itself, cross-case concurrency
from ``RunPolicy.max_concurrency``). Replay mode lands in Phase 4a and is
signalled explicitly rather than half-implemented.
"""

from __future__ import annotations

import asyncio
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
from kbws_forge_runtime.models import ChatResult
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
    ) -> EvalRun:
        """Execute a suite and persist the resulting :class:`EvalRun`."""
        if mode == "replay":
            raise NotImplementedError("replay mode lands in Phase 4a")
        if mode != "live":
            raise ValueError(f"unknown eval mode: {mode!r}")

        eval_run = EvalRun(
            suite_id=suite.id,
            agent_id=suite.agent_id,
            repetitions=suite.repetitions,
            provenance=self._provenance(suite, provenance),
        )

        cases = [
            case for case in suite.cases if not case_ids or case.id in case_ids
        ]
        semaphore: asyncio.Semaphore | None = None
        if suite.policy is not None and suite.policy.max_concurrency:
            semaphore = asyncio.Semaphore(suite.policy.max_concurrency)

        results = await asyncio.gather(
            *(self._run_case(suite, case, semaphore) for case in cases),
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
            repetitions=suite.repetitions,
            provenance=eval_run.provenance,
            cases=tuple(case_results),
        )
        await self._store.save(eval_run)
        return eval_run

    def _provenance(self, suite, extras: dict[str, Any] | None) -> dict[str, Any]:
        policy = suite.policy or getattr(self._runtime, "_default_policy", None)
        snapshot = policy.model_dump(mode="json") if policy else {}
        return {
            "policy": snapshot,
            "git_sha": _git_sha(),
            "repetitions": suite.repetitions,
            **(extras or {}),
        }

    # --- case execution ---

    async def _run_case(
        self,
        suite,
        case: EvalCase,
        semaphore: asyncio.Semaphore | None,
    ) -> EvalCaseResult:
        started = monotonic()
        executions: list[tuple[ChatResult, list[dict[str, Any]]]] = []
        errors: list[str] = []
        all_run_ids: list[str] = []

        for _ in range(suite.repetitions):
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

        graders = case.graders or suite.graders
        if not graders:
            return EvalCaseResult(
                case_id=case.id,
                run_ids=tuple(all_run_ids),
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
            run_ids=tuple(all_run_ids),
            status=status,
            score=sum(scored) / len(scored) if scored else None,
            graders=tuple(grader_results),
            failure_reasons=tuple(failure_reasons),
            duration_ms=(monotonic() - started) * 1000,
        )

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
