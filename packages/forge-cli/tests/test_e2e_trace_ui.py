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
    *(
        str(Path(os.environ.get(variable, default)) / executable)
        for variable, default, executable in (
            (
                "PROGRAMFILES",
                "C:/Program Files",
                "Google/Chrome/Application/chrome.exe",
            ),
            (
                "PROGRAMFILES(X86)",
                "C:/Program Files (x86)",
                "Google/Chrome/Application/chrome.exe",
            ),
            (
                "LOCALAPPDATA",
                "C:/Users/Default/AppData/Local",
                "Google/Chrome/Application/chrome.exe",
            ),
            (
                "PROGRAMFILES",
                "C:/Program Files",
                "Microsoft/Edge/Application/msedge.exe",
            ),
            (
                "PROGRAMFILES(X86)",
                "C:/Program Files (x86)",
                "Microsoft/Edge/Application/msedge.exe",
            ),
        )
    ),
)


def _skip_if_unavailable() -> None:
    if os.environ.get("FORGE_E2E") != "1":
        pytest.skip(
            "set FORGE_E2E=1 to run the browser e2e (needs Chrome + npx playwright)"
        )
    if shutil.which("node") is None or shutil.which("npm") is None:
        pytest.skip("Node.js/npm not found; install Node.js to run the browser e2e")


def _browser_executable() -> str | None:
    configured = os.environ.get("FORGE_BROWSER_EXECUTABLE")
    if configured:
        if not Path(configured).is_file():
            pytest.fail(
                "FORGE_BROWSER_EXECUTABLE does not point to a browser executable"
            )
        return configured
    return next((path for path in _CHROME_PATHS if Path(path).is_file()), None)


def _ensure_playwright() -> None:
    """Install @playwright/test into e2e/ on first opt-in run."""
    node_modules = _PKG_ROOT / "e2e" / "node_modules" / "@playwright" / "test"
    if node_modules.exists():
        return
    result = subprocess.run(
        [shutil.which("npm"), "ci", "--no-audit", "--no-fund"],
        cwd=_PKG_ROOT / "e2e",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(
            "could not npm ci @playwright/test in e2e/ "
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
        browser = _browser_executable()
        if browser:
            env["FORGE_BROWSER_EXECUTABLE"] = browser
        playwright_cli = (
            _PKG_ROOT / "e2e" / "node_modules" / "@playwright" / "test" / "cli.js"
        )
        result = subprocess.run(
            [
                shutil.which("node"),
                str(playwright_cli),
                "test",
                "--config",
                "e2e/playwright.config.mjs",
            ],
            cwd=_PKG_ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
            check=False,
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
