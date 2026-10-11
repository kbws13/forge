// Browser e2e for the Forge Trace UI.
//
// Agent API is a local Node stub (deterministic SSE runs + trace query API).
// UI is modeled on Google ADK / LangSmith: flat session list, session
// workspace with a run strip, and a waterfall trace view. It auto-connects on
// load (settings pre-seeded via localStorage) and auto-refreshes, so runs
// created by other clients appear without any click.
//
// Run: FORGE_E2E=1 uv run pytest tests/test_e2e_trace_ui.py -v
import { test, expect } from "@playwright/test";
import { startStubService } from "./stub_server.mjs";

let stub;

test.beforeAll(async () => {
  stub = await startStubService();
});

test.afterAll(async () => {
  await stub?.close();
});

test("trace ui: ADK-style sessions, waterfall, auto-connect, edge cases", async ({ page }, testInfo) => {
  const consoleErrors = [];
  page.on("console", (m) => {
    if (m.type() === "error") consoleErrors.push(m.text());
  });
  page.on("pageerror", (e) => consoleErrors.push(String(e)));

  const stubApiUrl = `http://127.0.0.1:${stub.port}/api/v1`;

  await page.addInitScript(
    (url) => localStorage.setItem("forge-trace-settings", JSON.stringify({ apiUrl: url, apiKey: "test-key" })),
    stubApiUrl,
  );

  const font = (sel) =>
    page.locator(sel).first().evaluate((el) => getComputedStyle(el).fontFamily);
  const expectSans = async (sel) => {
    const f = await font(sel);
    expect(
      f.includes("system-ui") || f.includes("-apple-system"),
      `${sel} should be sans, got ${f}`,
    ).toBe(true);
  };
  const expectMono = async (sel) => {
    const f = await font(sel);
    expect(f.includes("ui-monospace"), `${sel} should be mono, got ${f}`).toBe(true);
  };

  await page.goto("/", { waitUntil: "networkidle" });

  // 自动连接 + 首次加载自动选中最新会话（无需任何点击）
  await expect(page.locator("#connection-status")).toHaveText(/1 agent/, { timeout: 10000 });
  await expect(page.locator("#history-count")).toHaveText("1 session · 1 run");
  await expect(page.locator(".session-item")).toHaveCount(1);
  await expect(page.locator(".session-workspace-id")).toBeVisible();
  await expect(page.locator(".turn-card")).toHaveCount(1);

  // 选中 run → 瀑布 trace 渲染（model/tool/stream 都在）
  await page.locator(".turn-card").first().click();
  await expect(page.locator(".timeline-event").first()).toBeVisible({ timeout: 10000 });
  await expect(page.locator(".invocation-header")).toBeVisible();
  await expect(page.locator(".event-bar.model").first()).toBeVisible();
  const titles = await page.locator(".event-title").allTextContents();
  expect(titles.join(" ")).toContain("Tool completed");
  expect(titles.join(" ")).toContain("Response stream");

  await expect(page.getByRole("tab", { name: "Eval", exact: true })).toHaveCount(0);

  // 模拟“另一个客户端”（node fetch，不经 UI）连发两条同会话 run
  for (const message of ["外部请求一", "外部请求二"]) {
    const res = await fetch(`${stubApiUrl}/chat_stream`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ agent_id: "test_agent", user_id: "external", message }),
    });
    expect(res.ok).toBe(true);
  }
  // 自动刷新：3 runs 分 2 个会话
  await expect(page.locator("#history-count")).toHaveText("2 sessions · 3 runs", { timeout: 20000 });
  await expect(page.locator(".session-item")).toHaveCount(2);

  // 切到最新会话（外部）→ 会话内 2 个 run chip（同会话聚合）
  await page.locator(".session-item").nth(0).click();
  await expect(page.locator(".turn-card")).toHaveCount(2);

  // 过滤：只显示匹配的会话（ADK 的 filter）
  await page.locator("#session-filter").fill("external");
  await expect(page.locator(".session-item")).toHaveCount(1);
  await page.locator("#session-filter").fill("");
  await expect(page.locator(".session-item")).toHaveCount(2);

  // 边界：超长 prompt 的 run 不导致页面横向溢出
  const longPrompt = "长".repeat(3000);
  const longRun = await fetch(`${stubApiUrl}/chat_stream`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ agent_id: "test_agent", user_id: "long", message: longPrompt }),
  });
  expect(longRun.ok).toBe(true);
  await expect(page.locator("#history-count")).toHaveText("3 sessions · 4 runs", { timeout: 20000 });
  await page.locator(".session-item").first().click();
  await page.locator(".turn-card").first().click();
  await expect(page.locator(".timeline-event").first()).toBeVisible({ timeout: 10000 });
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
  const nameEllipsized = await page
    .locator(".session-name")
    .first()
    .evaluate((node) => node.scrollWidth > node.clientWidth);
  expect(nameEllipsized).toBe(true);

  // 扩展性：一个会话塞入 20 轮对话，Turns 面板滚动、任选一轮都能正常审查
  for (let i = 0; i < 20; i += 1) {
    await fetch(`${stubApiUrl}/chat_stream`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ agent_id: "test_agent", user_id: "bulk", message: `批量轮次 ${i}` }),
    });
  }
  await expect(page.locator("#history-count")).toHaveText("4 sessions · 24 runs", { timeout: 30000 });
  await page.locator(".session-item").first().click();
  await expect(page.locator(".turn-card")).toHaveCount(20);
  // 选中间一轮（第 10 个）→ 主区渲染对应执行树
  await page.locator(".turn-card").nth(9).click();
  await expect(page.locator(".timeline-event").first()).toBeVisible({ timeout: 10000 });
  await expect(page.locator(".turn-card").nth(9)).toHaveClass(/active/);

  // 刷新 → 依然自动连接，数据从服务端恢复
  await page.reload({ waitUntil: "networkidle" });
  await expect(page.locator("#connection-status")).toHaveText(/1 agent/, { timeout: 10000 });
  await expect(page.locator("#history-count")).toHaveText("4 sessions · 24 runs", { timeout: 10000 });

  // 主题切换
  const themeBefore = await page.evaluate(() => document.documentElement.dataset.theme);
  await page.locator("#theme-toggle").click();
  const themeAfter = await page.evaluate(() => document.documentElement.dataset.theme);
  expect(themeAfter).not.toBe(themeBefore);

  // 字体纪律：UI 镀铬 = sans；数据/代码 = mono
  for (const sel of [".tab", ".brand", "#connection-status", ".session-name", ".total-latency"]) {
    await expectSans(sel);
  }
  for (const sel of [".trace-label", ".stat-value", ".session-count", ".invocation-id"]) {
    await expectMono(sel);
  }

  // 无 console 错误
  expect(consoleErrors).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("trace-workspace.png"), fullPage: true });
});

test("trace ui: running details refresh and usage completeness stays visible", async ({ page }, testInfo) => {
  const apiUrl = `http://127.0.0.1:${stub.port}/api/v1`;
  const unexpectedRequests = [];
  const run = {
    run_id: "lifecycle-run",
    agent_id: "test_agent",
    session_id: "lifecycle-session",
    prompt: "Observe an interrupted run",
    status: "running",
    started_at: "2026-10-11T00:00:00.000Z",
    model_calls: 1,
    tool_calls: 0,
    usage: { input_tokens: 0, output_tokens: 0, total_tokens: 0, completeness: "unknown" },
    events: [{ event_id: "start", sequence: 1, type: "run_started", created_at: "2026-10-11T00:00:00.000Z" }],
  };
  await page.route(`${apiUrl}/**`, async (route) => {
    const url = new URL(route.request().url());
    let data;
    if (url.pathname.endsWith("/agents")) {
      data = [{ agent_id: "test_agent", name: "Test Agent" }];
    } else if (url.pathname.endsWith("/traces")) {
      const { events, ...summary } = run;
      data = [summary];
    } else if (url.pathname.endsWith(`/traces/${run.run_id}`)) {
      data = run;
    } else {
      unexpectedRequests.push(url.pathname);
      return route.fulfill({ status: 404, json: { info: "unexpected endpoint" } });
    }
    return route.fulfill({ json: { code: 0, info: "ok", data } });
  });
  await page.addInitScript(
    (url) => localStorage.setItem("forge-trace-settings", JSON.stringify({ apiUrl: url })),
    apiUrl,
  );
  await page.goto("/", { waitUntil: "networkidle" });
  const stat = (label) => page.locator(".stat").filter({ has: page.locator(".stat-label", { hasText: new RegExp(`^${label}$`) }) });
  await expect(stat("Tokens")).toHaveText("TokensUnknown");
  await expect(stat("Status")).toHaveText("Statusrunning");
  await page.screenshot({ path: testInfo.outputPath("trace-running-unknown.png"), fullPage: true });

  run.status = "interrupted";
  run.completed_at = "2026-10-11T00:00:01.000Z";
  run.usage = { input_tokens: 12, output_tokens: 5, total_tokens: 17, completeness: "partial" };
  run.events_dropped = 3;
  run.events.push({ event_id: "end", sequence: 2, type: "run_interrupted", reason: "Process restarted", created_at: run.completed_at });
  await page.locator("#refresh-history").click();
  await expect(stat("Tokens")).toHaveText("Tokens17 (partial)");
  await expect(stat("Status")).toHaveText("Statusinterrupted");
  await expect(stat("Events dropped")).toHaveText("Events dropped3");
  await expect(page.locator(".event-title").last()).toHaveText("Run interrupted");
  await page.screenshot({ path: testInfo.outputPath("trace-interrupted-partial-usage.png"), fullPage: true });

  run.status = "cancelled";
  run.usage = { input_tokens: 0, output_tokens: 0, total_tokens: 0, completeness: "complete" };
  run.events[1] = { ...run.events[1], event_id: "cancelled", type: "run_cancelled" };
  await page.locator("#refresh-history").click();
  await expect(stat("Tokens")).toHaveText("Tokens0");
  await expect(stat("Status")).toHaveText("Statuscancelled");
  await expect(page.locator(".event-title").last()).toHaveText("Run cancelled");
  await page.screenshot({ path: testInfo.outputPath("trace-cancelled-zero.png"), fullPage: true });
  run.status = "failed";
  run.events[1] = { ...run.events[1], type: "run_failed", error_message: "Expected model failure" };
  await page.locator("#refresh-history").click();
  await expect(stat("Status")).toHaveText("Statusfailed");
  await expect(page.locator(".event-title").last()).toHaveText("Run failed");
  await page.screenshot({ path: testInfo.outputPath("trace-failed.png"), fullPage: true });
  expect(unexpectedRequests).toEqual([]);
});
