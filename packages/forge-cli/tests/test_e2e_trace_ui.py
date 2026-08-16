"""Browser e2e bridge for the Trace UI (opt-in, requires Chrome + Playwright).

Starts the real ``forge trace`` server on an ephemeral loopback port, then runs
the Playwright spec in ``e2e/`` against a hermetic Node stub of the agent API.

Opt-in: set ``FORGE_E2E=1`` (otherwise skipped, like the ``real_provider``
marker). Requires a Chrome/Chromium binary and ``npx playwright``; see
``e2e/playwright.config.mjs`` for the browser channel.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from threading import Thread

import pytest

from kbws_forge_cli.trace_server import create_trace_server

pytestmark = pytest.mark.e2e

_PKG_ROOT = Path(__file__).resolve().parents[1]

_CHROME_PATHS = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
)


def _skip_if_unavailable() -> None:
    if os.environ.get("FORGE_E2E") != "1":
        pytest.skip("set FORGE_E2E=1 to run the browser e2e (needs Chrome + npx playwright)")
    if shutil.which("npx") is None:
        pytest.skip("npx not found; install Node.js to run the browser e2e")
    if not any(Path(path).exists() for path in _CHROME_PATHS):
        pytest.skip("no Chrome/Chromium binary found; install one or run `npx playwright install chromium`")


def _ensure_playwright() -> None:
    """Install @playwright/test into e2e/ on first opt-in run."""
    node_modules = _PKG_ROOT / "e2e" / "node_modules" / "@playwright" / "test"
    if node_modules.exists():
        return
    result = subprocess.run(
        ["npm", "install", "--no-audit", "--no-fund"],
        cwd=_PKG_ROOT / "e2e",
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        pytest.skip(
            "could not npm install @playwright/test in e2e/ "
            f"({result.stderr.strip().splitlines()[-1] if result.stderr.strip() else 'unknown'})"
        )


def test_trace_ui_browser_flow() -> None:
    _skip_if_unavailable()
    _ensure_playwright()

    # 起真实的 trace 服务（静态 UI + config.json），端口随机
    server = create_trace_server(api_url="http://127.0.0.1:9/api/v1", port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        env = {
            **os.environ,
            "TRACE_UI_URL": f"http://127.0.0.1:{server.server_port}",
        }
        playwright_bin = _PKG_ROOT / "e2e" / "node_modules" / ".bin" / "playwright"
        result = subprocess.run(
            [
                str(playwright_bin),
                "test",
                "--config",
                "e2e/playwright.config.mjs",
            ],
            cwd=_PKG_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode != 0:
            sys.stdout.write(result.stdout)
            sys.stderr.write(result.stderr)
            pytest.fail(
                "Trace UI browser e2e failed; rerun with FORGE_E2E=1 "
                "uv run pytest tests/test_e2e_trace_ui.py -v -s for details"
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
