"""Eval report writers: JSON + JUnit4 XML (CI-parseable)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape


def write_json_report(run: dict[str, Any], path: str | Path) -> Path:
    target = Path(path)
    target.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def write_junit_report(run: dict[str, Any], path: str | Path) -> Path:
    """JUnit4 XML: one <testcase> per eval case; failures carry the reason."""
    totals = run.get("totals", {})
    cases = run.get("cases", [])
    time = sum(float(case.get("duration_ms") or 0) for case in cases) / 1000
    tests = totals.get("evaluated", len(cases))
    failures = totals.get("failed", 0)
    skipped = totals.get("not_evaluated", 0)

    lines: list[str] = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append(
        f'<testsuites tests="{tests}" failures="{failures}" skipped="{skipped}" '
        f'time="{time:.3f}">'
    )
    lines.append(
        f'  <testsuite name="{escape(run.get("suite_id", ""))}" '
        f'tests="{tests}" failures="{failures}" skipped="{skipped}" time="{time:.3f}">'
    )
    for case in cases:
        name = escape(case.get("case_id", ""))
        classname = f"eval.{escape(run.get('suite_id', ''))}"
        duration = float(case.get("duration_ms") or 0) / 1000
        status = case.get("status", "not_evaluated")
        if status == "passed":
            lines.append(
                f'    <testcase name="{name}" classname="{classname}" time="{duration:.3f}"/>'
            )
        elif status == "not_evaluated":
            lines.append(
                f'    <testcase name="{name}" classname="{classname}" time="{duration:.3f}">'
                f'<skipped message="{escape(_reason(case))}"/></testcase>'
            )
        else:
            lines.append(
                f'    <testcase name="{name}" classname="{classname}" time="{duration:.3f}">'
                f'<failure message="{escape(_reason(case))}">{escape(_reason(case))}'
                f"</failure></testcase>"
            )
    lines.append("  </testsuite>")
    lines.append("</testsuites>")

    target = Path(path)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def _reason(case: dict[str, Any]) -> str:
    reasons = case.get("failure_reasons") or []
    return "; ".join(str(reason) for reason in reasons) if reasons else case.get("status", "")


__all__ = ["write_json_report", "write_junit_report"]
