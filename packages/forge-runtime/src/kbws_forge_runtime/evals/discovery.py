"""Eval suite discovery: ``evals/*.py`` modules exporting ``suite``/``suites``.

Convention mirrors ``agents/``: code-first, one module per suite (or several).
A module may export a single ``suite`` object or a ``suites`` list. Modules
without either export (e.g. shared graders) are skipped.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

from kbws_forge_runtime.evals.models import EvalSuite


def load_eval_suites(evals_dir: str | Path) -> list[EvalSuite]:
    """Scan ``evals_dir`` and return every discovered suite."""
    root = Path(evals_dir).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"evals directory does not exist: {root}")
    if str(root.parent) not in sys.path:
        sys.path.insert(0, str(root.parent))

    suites: list[EvalSuite] = []
    for module_file in sorted(root.glob("*.py")):
        if module_file.name == "__init__.py":
            continue
        module = importlib.import_module(f"{root.name}.{module_file.stem}")
        value = getattr(module, "suites", None)
        if value is None:
            value = getattr(module, "suite", None)
        if value is None:
            continue
        items = value if isinstance(value, (list, tuple)) else [value]
        for item in items:
            if not isinstance(item, EvalSuite):
                raise ValueError(
                    f"{module_file} must export an `EvalSuite` (got {type(item).__name__})"
                )
            suites.append(item)

    seen: set[str] = set()
    for suite in suites:
        if suite.id in seen:
            raise ValueError(f"duplicate eval suite id: {suite.id!r}")
        seen.add(suite.id)
    return suites


__all__ = ["load_eval_suites"]
