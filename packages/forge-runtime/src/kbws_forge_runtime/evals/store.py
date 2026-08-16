"""EvalStore: persist eval runs (mirrors the TraceStore persistence style).

Each eval run is one JSON file in ``logs/evals/<eval_run_id>.json`` (atomic
write, bounded). ``by_run_id`` answers "which eval cases touched this agent
run" — the link used by the trace UI and by replay.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from kbws_forge_runtime.evals.models import EvalRun

_DEFAULT_DIR = "logs/evals"


class EvalStore:
    def __init__(
        self,
        *,
        persist_dir: str | Path | None = None,
        max_runs: int = 200,
    ) -> None:
        self._persist_dir = Path(persist_dir or _DEFAULT_DIR)
        self._max_runs = max(1, int(max_runs))
        self._runs: dict[str, EvalRun] = {}
        self._order: list[str] = []
        self._load()

    async def save(self, eval_run: EvalRun) -> None:
        """Upsert a run; persist when it reaches a terminal state."""
        self._runs[eval_run.eval_run_id] = eval_run
        if eval_run.eval_run_id not in self._order:
            self._order.append(eval_run.eval_run_id)
        self._trim()
        if eval_run.status in {"finished", "failed"}:
            self._persist(eval_run)

    def list_runs(self, limit: int = 100) -> list[dict[str, Any]]:
        """Run summaries, newest first (no per-case payloads)."""
        selected = self._order[-max(0, limit) :] if limit else self._order
        return [
            self._summary(self._runs[run_id]) for run_id in reversed(selected)
        ]

    def get_run(self, eval_run_id: str) -> dict[str, Any] | None:
        run = self._runs.get(eval_run_id)
        if run is None:
            return None
        return run.model_dump(mode="json")

    def by_run_id(self, run_id: str) -> list[dict[str, Any]]:
        """Eval case results that reference an agent run (UI/replay link)."""
        matches: list[dict[str, Any]] = []
        for run in reversed(self._runs.values()):
            for case in run.cases:
                if run_id in case.run_ids:
                    matches.append(
                        {
                            "eval_run_id": run.eval_run_id,
                            "suite_id": run.suite_id,
                            "case_id": case.case_id,
                            "status": case.status,
                            "score": case.score,
                            "failure_reasons": case.failure_reasons,
                            "graders": case.graders,
                        }
                    )
        return matches

    def delete_run(self, eval_run_id: str) -> bool:
        if eval_run_id not in self._runs:
            return False
        self._runs.pop(eval_run_id)
        self._order.remove(eval_run_id)
        self._delete_file(eval_run_id)
        return True

    def clear(self) -> None:
        self._runs.clear()
        self._order.clear()
        try:
            for path in self._persist_dir.glob("*.json"):
                path.unlink()
        except OSError:
            pass

    # --- internal ---

    def _trim(self) -> None:
        while len(self._order) > self._max_runs:
            self._runs.pop(self._order.pop(0), None)

    def _summary(self, run: EvalRun) -> dict[str, Any]:
        data = run.model_dump(mode="json", exclude={"cases"})
        data["totals"] = run.totals
        data["average_score"] = run.average_score
        return data

    def _path(self, eval_run_id: str) -> Path:
        return self._persist_dir / f"{eval_run_id}.json"

    def _persist(self, eval_run: EvalRun) -> None:
        try:
            self._persist_dir.mkdir(parents=True, exist_ok=True)
            target = self._path(eval_run.eval_run_id)
            tmp = target.with_name(target.name + ".tmp")
            tmp.write_text(
                json.dumps(eval_run.model_dump(mode="json"), ensure_ascii=False, indent=1),
                encoding="utf-8",
            )
            tmp.replace(target)
        except OSError:
            return  # 持久化尽力而为，失败不阻断

    def _delete_file(self, eval_run_id: str) -> None:
        try:
            self._path(eval_run_id).unlink()
        except OSError:
            pass

    def _load(self) -> None:
        try:
            paths = sorted(self._persist_dir.glob("*.json"))
        except OSError:
            return
        for path in paths[-self._max_runs :]:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                self._runs[data["eval_run_id"]] = EvalRun.model_validate(data)
                self._order.append(data["eval_run_id"])
            except (OSError, ValueError, KeyError):
                continue


__all__ = ["EvalStore"]
