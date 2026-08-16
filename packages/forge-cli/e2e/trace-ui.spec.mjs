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

test("trace ui: ADK-style sessions, waterfall, auto-connect, edge cases", async ({ page }) => {
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

  // eval 徽章：foreign run 预置 1 过 1 挂
  await expect(page.locator(".eval-badge")).toHaveCount(1);
  await expect(page.locator(".eval-badge")).toHaveText("1/2");
  await expect(page.locator(".eval-badge")).toHaveClass(/failed/);

  // Eval tab：逐 case 得分 + 失败原因
  await page.locator('[data-tab="eval"]').click();
  await expect(page.locator(".eval-case")).toHaveCount(2);
  await expect(page.locator(".eval-reason").first()).toContainText("tools not called");
  await expect(page.locator(".eval-case-head").first()).toContainText("add_tool");
  await page.locator('[data-tab="turns"]').click();

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

  // Evals 视图：切换后显示评估历史 → 选中 → 逐 case 结果 → 点 case 跳进对应 run 的执行流
  await page.locator("#view-evals").click();
  await expect(page.locator("#view-evals")).toHaveClass(/active/);
  await expect(page.locator(".session-item")).toHaveCount(1);
  await page.locator(".session-select").first().click();
  await expect(page.locator(".eval-case-row")).toHaveCount(2);
  await expect(page.locator(".eval-case-row-score").first()).toHaveText("1.00");
  await expect(page.locator(".invocation-header")).toContainText("1/2 passed");
  // 点失败的 case → 跳回 Trace 视图并打开对应 run
  await page.locator(".eval-case-row").nth(1).click();
  await expect(page.locator("#view-trace")).toHaveClass(/active/);
  await expect(page.locator(".timeline-event").first()).toBeVisible({ timeout: 10000 });
  // 回到 Trace 视图后徽章仍在（run 的 eval 结果）
  await expect(page.locator(".eval-badge").first()).toBeVisible();
  await page.locator("#view-trace").click();

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
});
