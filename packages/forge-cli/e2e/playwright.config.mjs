// Playwright config for the Forge Trace UI browser e2e.
// Run via: FORGE_E2E=1 uv run pytest tests/test_e2e_trace_ui.py -v
export default {
  testDir: ".",
  testMatch: "**/*.spec.mjs",
  outputDir: "test-results",
  fullyParallel: false,
  workers: 1,
  timeout: 120_000,
  expect: { timeout: 10_000 },
  use: {
    // Uses the locally installed Chrome when present; otherwise run
    // `npx playwright install chromium` and drop the channel line.
    channel: "chrome",
    headless: true,
    viewport: { width: 1440, height: 860 },
    baseURL: process.env.TRACE_UI_URL || "http://127.0.0.1:8765",
  },
  reporter: [["list"]],
};
