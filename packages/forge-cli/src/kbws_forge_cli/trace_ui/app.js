"use strict";

const MAX_RUNS = 100;
const SETTINGS_KEY = "forge-trace-settings";
const THEME_KEY = "forge-trace-theme";
const REFRESH_MS = 5000;
const RETRY_MS = 8000;

const state = {
  apiUrl: "",
  apiKey: "",
  agents: [],
  runs: [],
  activeSessionKey: null,
  activeRunId: null,
  activeEventId: null,
  inspectorTab: "turns",
  filter: "",  connected: false,
  connecting: false,
  loadingRunId: null,
  autoSelected: false,
  refreshTimer: null,
  retryTimer: null,
  renderFrame: null,
};

const elements = {
  connectionForm: document.querySelector("#connection-form"),
  connectBar: document.querySelector("#connect-bar"),
  apiUrl: document.querySelector("#api-url"),
  apiKey: document.querySelector("#api-key"),
  connectButton: document.querySelector("#connect-button"),
  connectionStatus: document.querySelector("#connection-status"),
  refreshHistory: document.querySelector("#refresh-history"),
  clearHistory: document.querySelector("#clear-history"),
  themeToggle: document.querySelector("#theme-toggle"),
  sessionFilter: document.querySelector("#session-filter"),
  historyList: document.querySelector("#history-list"),
  historyCount: document.querySelector("#history-count"),
  storageLabel: document.querySelector("#storage-label"),
  runView: document.querySelector("#run-view"),
  inspectorContent: document.querySelector("#inspector-content"),
  tabs: Array.from(document.querySelectorAll("[data-tab]")),
};

init();

async function init() {
  bindEvents();
  applyTheme(loadTheme());

  try {
    const response = await fetch("/config.json", { cache: "no-store" });
    const config = await response.json();
    state.apiUrl = normalizeApiUrl(config.apiUrl || "");
  } catch (error) {
    setStatus("error", readableError(error));
  }

  // 记住的连接设置（本地调试工具，仅存 127.0.0.1 页面）
  try {
    const saved = JSON.parse(localStorage.getItem(SETTINGS_KEY) || "{}");
    if (saved.apiUrl) {
      state.apiUrl = saved.apiUrl;
      state.apiKey = saved.apiKey || "";
    }
  } catch {
    /* ignore */
  }
  elements.apiUrl.value = state.apiUrl;
  elements.apiKey.value = state.apiKey;

  renderAll();
  connectToApi();
}

function bindEvents() {
  elements.connectionForm.addEventListener("submit", connectToApi);
  elements.refreshHistory.addEventListener("click", () => {
    setStatus("connecting", "Refreshing");
    loadServiceTraces().finally(() => {
      if (state.connected) {
        setStatus("connected", `${state.agents.length} agent${state.agents.length === 1 ? "" : "s"}`);
      }
    });
  });
  elements.clearHistory.addEventListener("click", clearHistory);
  elements.themeToggle.addEventListener("click", () => {
    applyTheme(currentTheme() === "dark" ? "light" : "dark");
  });
  elements.sessionFilter.addEventListener("input", () => {
    state.filter = elements.sessionFilter.value.trim().toLowerCase();
    renderHistory();
  });
  for (const tab of elements.tabs) {
    tab.addEventListener("click", () => {
      state.inspectorTab = tab.dataset.tab;
      renderInspector();
    });
  }
}

// --- 连接（自动） ---

async function connectToApi(event) {
  event?.preventDefault();
  if (state.connecting) {
    return;
  }
  state.connecting = true;
  setStatus("connecting", "Connecting");
  elements.connectButton.disabled = true;

  try {
    state.apiUrl = normalizeApiUrl(elements.apiUrl.value || state.apiUrl);
    state.apiKey = elements.apiKey.value;
    elements.apiUrl.value = state.apiUrl;

    const response = await fetch(`${state.apiUrl}/agents`, {
      headers: authHeaders(),
      cache: "no-store",
    });
    if (!response.ok) {
      throw new Error(await responseError(response));
    }
    const payload = await response.json();
    const agents = Array.isArray(payload) ? payload : payload.data;
    if (!Array.isArray(agents)) {
      throw new Error("The agents endpoint returned an unsupported response");
    }
    state.agents = agents.filter((agent) => agent && typeof agent.agent_id === "string");
    state.connected = true;
    elements.connectBar.hidden = true;
    saveSettings();
    scheduleAutoRefresh();
    await loadServiceTraces();
    setStatus("connected", `${state.agents.length} agent${state.agents.length === 1 ? "" : "s"}`);
  } catch (error) {
    state.connected = false;
    state.agents = [];
    elements.connectBar.hidden = false;
    setStatus("error", readableConnectionError(error));
  } finally {
    state.connecting = false;
    elements.connectButton.disabled = false;
    renderAll();
    scheduleRetry();
  }
}

function scheduleRetry() {
  if (state.connected || state.retryTimer) {
    return;
  }
  state.retryTimer = setTimeout(() => {
    state.retryTimer = null;
    connectToApi();
  }, RETRY_MS);
}

function scheduleAutoRefresh() {
  if (state.refreshTimer) {
    return;
  }
  state.refreshTimer = setInterval(() => {
    if (state.connected) {
      loadServiceTraces();
    }
  }, REFRESH_MS);
}

function saveSettings() {
  try {
    localStorage.setItem(
      SETTINGS_KEY,
      JSON.stringify({ apiUrl: state.apiUrl, apiKey: state.apiKey }),
    );
  } catch {
    /* ignore */
  }
}

function authHeaders() {
  return state.apiKey ? { "X-API-Key": state.apiKey } : {};
}

// --- trace 数据（服务端为事实源） ---

async function loadServiceTraces() {
  if (!state.connected || state.agents.length === 0) {
    return;
  }
  try {
    const response = await fetch(`${state.apiUrl}/traces?limit=${MAX_RUNS}`, {
      headers: authHeaders(),
      cache: "no-store",
    });
    if (!response.ok) {
      throw new Error(await responseError(response));
    }
    const payload = await response.json();
    const summaries = Array.isArray(payload) ? payload : payload.data;
    if (!Array.isArray(summaries)) {
      throw new Error("The traces endpoint returned an unsupported response");
    }
    state.runs = summaries
      .filter((run) => run && typeof run.run_id === "string")
      .map((run) => {
        const record = normalizeRunRecord(run);
        // 保留本地已加载的 events，避免重复拉取详情
        const existing = findRun(run.run_id);
        if (existing && existing.events.length > 0) {
          record.events = existing.events;
          record.response_text = existing.response_text;
          record.evalResults = existing.evalResults;
          if (existing.summary) {
            record.summary = existing.summary;
          }
        }
        return record;
      });
    if (state.activeRunId && !findRun(state.activeRunId)) {
      state.activeRunId = null;
      state.activeEventId = null;
    }
    if (state.activeSessionKey && !sessionGroups().some((g) => g.key === state.activeSessionKey)) {
      state.activeSessionKey = null;
      state.activeRunId = null;
    }
    // 首次加载：自动选中最新会话及其最新 run（ADK 式：打开即见内容）
    if (!state.autoSelected && state.runs.length > 0) {
      state.autoSelected = true;
      const groups = sessionGroups();
      const group = groups.find((g) => g.key === state.activeSessionKey) || groups[0];
      selectSession(group.key, false);
    }
  } catch (error) {
    if (state.connected) {
      elements.connectionStatus.title = readableConnectionError(error);
    }
  }
  renderAll();
}

async function fetchRunDetail(runId) {
  const run = findRun(runId);
  if (!run || run.events.length > 0) {
    return;
  }
  state.loadingRunId = runId;
  renderAll();
  try {
    const [detailResponse, evalResponse] = await Promise.all([
      fetch(`${state.apiUrl}/traces/${encodeURIComponent(runId)}`, {
        headers: authHeaders(),
        cache: "no-store",
      }),
      fetch(`${state.apiUrl}/traces/${encodeURIComponent(runId)}/eval`, {
        headers: authHeaders(),
        cache: "no-store",
      }),
    ]);
    if (!detailResponse.ok) {
      throw new Error(await responseError(detailResponse));
    }
    const payload = await detailResponse.json();
    const full = Array.isArray(payload) ? payload : payload.data;
    if (!full || !Array.isArray(full.events)) {
      throw new Error("The trace detail endpoint returned an unsupported response");
    }
    const merged = normalizeRunRecord(full);
    merged.events = full.events;
    merged.response_text = messageText(full.message) || run.response_text || "";
    if (evalResponse.ok) {
      const evalPayload = await evalResponse.json();
      const results = Array.isArray(evalPayload) ? evalPayload : evalPayload.data;
      if (Array.isArray(results)) {
        merged.evalResults = results;
      }
    }
    const index = state.runs.indexOf(run);
    if (index !== -1) {
      state.runs[index] = merged;
    }
    if (state.activeRunId === runId) {
      state.activeEventId = displayEvents(merged.events).at(-1)?.event_id || null;
    }
  } catch (error) {
    elements.connectionStatus.title = readableConnectionError(error);
  } finally {
    state.loadingRunId = null;
  }
  renderAll();
}

async function deleteRun(runId) {
  if (!window.confirm("Delete this trace from the server?")) {
    return;
  }
  try {
    const response = await fetch(`${state.apiUrl}/traces/${encodeURIComponent(runId)}`, {
      method: "DELETE",
      headers: authHeaders(),
      cache: "no-store",
    });
    if (!response.ok) {
      throw new Error(await responseError(response));
    }
    const removed = state.runs.find((run) => run.run_id === runId);
    state.runs = state.runs.filter((run) => run.run_id !== runId);
    if (removed && sessionKeyOf(removed) === state.activeSessionKey) {
      if (state.activeRunId === runId) {
        const group = sessionGroups().find((g) => g.key === state.activeSessionKey);
        state.activeRunId = group?.runs[0]?.run_id || null;
        state.activeEventId = null;
      }
    }
  } catch (error) {
    elements.connectionStatus.title = readableError(error);
  }
  renderAll();
}

async function deleteSession(sessionKey, count) {
  if (!window.confirm(`Delete this session and its ${count} run${count === 1 ? "" : "s"}?`)) {
    return;
  }
  try {
    for (const run of [...state.runs]) {
      if (sessionKeyOf(run) === sessionKey) {
        const response = await fetch(`${state.apiUrl}/traces/${encodeURIComponent(run.run_id)}`, {
          method: "DELETE",
          headers: authHeaders(),
          cache: "no-store",
        });
        if (!response.ok) {
          throw new Error(await responseError(response));
        }
      }
    }
    state.runs = state.runs.filter((run) => sessionKeyOf(run) !== sessionKey);
    if (state.activeSessionKey === sessionKey) {
      state.activeSessionKey = null;
      state.activeRunId = null;
      state.activeEventId = null;
    }
  } catch (error) {
    elements.connectionStatus.title = readableError(error);
  }
  renderAll();
}

async function clearHistory() {
  if (!window.confirm("Delete all traces from the server?")) {
    return;
  }
  try {
    const response = await fetch(`${state.apiUrl}/traces`, {
      method: "DELETE",
      headers: authHeaders(),
      cache: "no-store",
    });
    if (!response.ok) {
      throw new Error(await responseError(response));
    }
    state.runs = [];
    state.activeSessionKey = null;
    state.activeRunId = null;
    state.activeEventId = null;
    state.autoSelected = false;
  } catch (error) {
    elements.connectionStatus.title = readableError(error);
  }
  renderAll();
}

// --- 会话分组 ---

function sessionKeyOf(run) {
  return run.session_id || run.run_id;
}

function sessionGroups() {
  const byKey = new Map();
  for (const run of state.runs) {
    const key = sessionKeyOf(run);
    let group = byKey.get(key);
    if (!group) {
      group = { key, session_id: run.session_id || "", agent_id: run.agent_id, runs: [] };
      byKey.set(key, group);
    }
    group.runs.push(run);
  }
  const groups = [...byKey.values()];
  for (const group of groups) {
    group.runs.sort((left, right) =>
      (right.started_at || "").localeCompare(left.started_at || ""),
    );
  }
  groups.sort((left, right) =>
    (right.runs[0]?.started_at || "").localeCompare(left.runs[0]?.started_at || ""),
  );
  return groups;
}

function sessionDisplayName(group) {
  const first = group.runs.at(-1)?.prompt;
  if (first) {
    return first;
  }
  return group.session_id ? shortenId(group.session_id) : "No session";
}

function shortenId(value) {
  return value.length > 20 ? `${value.slice(0, 8)}…${value.slice(-4)}` : value;
}

// --- 渲染 ---

function renderAll() {
  renderHistory();
  renderRunView();
  renderInspector();
  renderTopbar();
}

function renderTopbar() {
  elements.refreshHistory.disabled = !state.connected;
  elements.clearHistory.disabled = state.runs.length === 0;
  elements.sessionFilter.disabled = !state.connected;
}

function renderHistory() {
  elements.historyList.replaceChildren();
  const groups = sessionGroups();
  const filtered = state.filter
    ? groups.filter(
        (g) =>
          sessionDisplayName(g).toLowerCase().includes(state.filter) ||
          g.session_id.toLowerCase().includes(state.filter),
      )
    : groups;
  elements.historyCount.textContent = `${filtered.length} ${filtered.length === 1 ? "session" : "sessions"} · ${state.runs.length} ${state.runs.length === 1 ? "run" : "runs"}`;

  if (!state.connected) {
    elements.historyList.append(make("p", "empty compact", "Connect to see runs"));
    return;
  }
  if (filtered.length === 0) {
    elements.historyList.append(make("p", "empty compact", state.filter ? "No matching sessions" : "No runs"));
    return;
  }

  for (const group of filtered) {
    elements.historyList.append(renderSessionItem(group));
  }
}

function renderSessionItem(group) {
  const item = make("div", `session-item${group.key === state.activeSessionKey ? " current" : ""}`);
  const select = make("button", "session-select");
  select.type = "button";
  select.addEventListener("click", () => selectSession(group.key, true));

  const latest = group.runs[0];
  const name = make("span", "session-name", sessionDisplayName(group));
  if (group.session_id && group.session_id !== sessionDisplayName(group)) {
    name.title = group.session_id;
  }
  const meta = make("span", "session-meta");
  meta.append(
    make("span", "session-date", formatDate(latest?.started_at)),
    make("span", `status-dot ${latest?.status || ""}`),
    make("span", "session-count", `${group.runs.length}`),
  );
  select.append(name, meta);

  const remove = make("button", "session-delete", "×");
  remove.type = "button";
  remove.title = "Delete session";
  remove.setAttribute("aria-label", `Delete session ${group.session_id || group.key}`);
  remove.addEventListener("click", (event) => {
    event.stopPropagation();
    deleteSession(group.key, group.runs.length);
  });

  item.append(select, remove);
  return item;
}

function selectSession(key, focusRun) {
  const group = sessionGroups().find((g) => g.key === key);
  if (!group) {
    return;
  }
  state.activeSessionKey = key;
  if (!focusRun || !group.runs.some((r) => r.run_id === state.activeRunId)) {
    state.activeRunId = group.runs[0]?.run_id || null;
    state.activeEventId = null;
  }
  renderAll();
  const run = findRun(state.activeRunId);
  if (run && run.events.length === 0 && state.connected) {
    fetchRunDetail(run.run_id);
  }
}

async function selectRun(runId) {
  const run = findRun(runId);
  if (!run) {
    return;
  }
  state.activeRunId = runId;
  state.activeSessionKey = sessionKeyOf(run);
  state.activeEventId = displayEvents(run.events).at(-1)?.event_id || null;
  renderAll();
  if (run.events.length === 0 && state.connected) {
    await fetchRunDetail(runId);
    renderAll();
  }
}

function renderRunView() {
  const scrollY = window.scrollY;
  elements.runView.replaceChildren();

  if (!state.connected) {
    elements.runView.append(emptyState("Not connected", "Waiting for the agent service…"));
    return;
  }
  const group = sessionGroups().find((g) => g.key === state.activeSessionKey);
  if (!group) {
    elements.runView.append(emptyState("No session selected", "Select a session from the history."));
    return;
  }

  const header = make("div", "session-workspace-header");
  header.append(
    make("span", "session-workspace-id", group.session_id ? shortenId(group.session_id) : "No session"),
    make("span", "session-workspace-meta", `${group.agent_id} · ${group.runs.length} runs`),
  );
  elements.runView.append(header);

  const run = findRun(state.activeRunId);
  if (!run) {
    elements.runView.append(emptyState("No run selected", "Pick a turn from the Turns panel."));
    return;
  }

  // 主区只展示选中 run 的执行树（LangSmith：主区 = trace，对话上下文在右侧面板）
  const panel = make("div", "trace-panel");
  const items = displayEvents(run.events);
  if (items.length === 0) {
    panel.append(
      make("p", "empty compact", state.loadingRunId === run.run_id ? "Loading events…" : "No events"),
    );
  } else {
    panel.append(renderInvocation(run, items));
    panel.append(renderTimeline(run, items));
  }
  elements.runView.append(panel);
  window.scrollTo(0, scrollY);
}

function renderInvocation(run, items) {
  const wrap = make("div", "invocation-wrap");
  const header = make("div", "invocation-header");
  header.append(
    make("span", "invocation-caption", "Invocation ID"),
    make("span", "invocation-id", shortenId(run.run_id)),
    make("span", "total-latency", `Total latency ${formatDuration(runDuration(run))}`),
  );
  wrap.append(header);

  const usage = run.usage || run.summary?.usage || {};
  const modelCalls = run.model_calls ?? countEvents(run, "model_started");
  const toolCalls = run.tool_calls ?? countEvents(run, "tool_started");
  const stats = make("div", "invocation-stats");
  stats.append(
    stat("Models", String(modelCalls)),
    stat("Tools", String(toolCalls)),
    stat("Tokens", formatNumber(usage.total_tokens ?? 0)),
    stat("Events", String(run.events.length)),
  );
  const badge = evalBadge(run);
  if (badge) {
    stats.append(stat("Eval", badge.label));
  }
  wrap.append(stats);
  return wrap;
}

function stat(label, value) {
  const node = make("span", "stat");
  node.append(make("span", "stat-label", label), make("span", "stat-value", value));
  return node;
}

function renderTimeline(run, items) {
  const container = make("div", "trace-container");
  const totalMs = waterfallTotal(run, items);
  container.append(renderTimelineRuler(totalMs));
  for (const event of items) {
    const row = make(
      "button",
      `timeline-event trace-row${event.event_id === state.activeEventId ? " selected" : ""}`,
    );
    row.type = "button";
    row.style.setProperty("--event-depth", String(eventDepth(event)));
    row.addEventListener("click", () => {
      state.activeEventId = event.event_id;
      state.inspectorTab = "details";
      renderRunView();
      renderInspector();
    });

    // 左段：缩进连接线 + 类型点 + mono 标签（ADK/LangSmith 式）
    const left = make("span", "trace-row-left");
    const indent = make("span", "trace-indent");
    for (let index = 0; index < Math.min(eventDepth(event), 6); index += 1) {
      indent.append(make("span", "indent-connector"));
    }
    const label = make("span", "event-title trace-label", eventTitle(event));
    const subtitle = eventSubtitle(event);
    if (subtitle && subtitle !== eventTitle(event)) {
      label.title = subtitle;
    }
    left.append(indent, make("span", `event-node ${eventGroup(event)}`), label);

    // 右段：瀑布条（Chrome F12 时序：共享时间轴上的比例定位条）
    const track = make("span", "trace-bar-container");
    const geometry = waterfallGeometry(run, event, totalMs);
    if (geometry) {
      const bar = make(
        "span",
        `event-bar trace-bar ${eventGroup(event)}${geometry.instant ? " instant" : ""}`,
      );
      bar.style.left = `${geometry.startPct}%`;
      if (!geometry.instant) {
        bar.style.width = `${Math.max(geometry.widthPct, 1)}%`;
        bar.textContent = formatDuration(geometry.durationMs);
        if (geometry.widthPct < 4) {
          track.append(
            make("span", "short-trace-bar-duration", formatDuration(geometry.durationMs)),
          );
        }
      }
      track.append(bar);
    }

    row.append(left, track);
    container.append(row);
  }
  return container;
}

function renderTimelineRuler(totalMs) {
  const ruler = make("div", "timeline-ruler");
  const label = make("span", "ruler-caption", "Time");
  const track = make("span", "ruler-track");
  const marks = [0, 0.25, 0.5, 0.75, 1];
  for (const fraction of marks) {
    const tick = make("span", "ruler-tick");
    tick.style.left = `${fraction * 100}%`;
    tick.append(make("span", "ruler-tick-line"));
    tick.append(
      make("span", "ruler-tick-label", formatDuration(totalMs * fraction)),
    );
    track.append(tick);
  }
  ruler.append(label, track);
  return ruler;
}

function waterfallTotal(run, items) {
  const fromSummary = run.duration_ms;
  if (fromSummary && fromSummary > 0) {
    return fromSummary;
  }
  const start = Date.parse(run.started_at);
  let max = 0;
  for (const event of items) {
    const t = Date.parse(event.created_at);
    if (Number.isFinite(t)) {
      max = Math.max(max, t - start);
    }
  }
  return max || 1;
}

function waterfallGeometry(run, event, totalMs) {
  const start = Date.parse(run.started_at);
  if (event.type === "text_stream") {
    const times = (event.source_events || [])
      .map((src) => Date.parse(src.created_at))
      .filter(Number.isFinite);
    if (times.length === 0) {
      return null;
    }
    const first = times[0] - start;
    const last = times.at(-1) - start;
    return {
      startPct: (first / totalMs) * 100,
      widthPct: Math.max(((last - first) / totalMs) * 100, 0.5),
      durationMs: last - first,
      instant: last - first < 1,
    };
  }
  const t = Date.parse(event.created_at);
  if (!Number.isFinite(t)) {
    return null;
  }
  const offset = t - start;
  // 只有 completed/failed 事件携带可计时的时长；其余（run 标记、message、started）都是瞬间点
  const isTimed = /_(finished|failed)$/.test(event.type || "");
  const duration = Number(event.duration_ms);
  if (isTimed && Number.isFinite(duration) && duration > 0) {
    const startPct = (offset / totalMs) * 100;
    const widthPct = Math.max((duration / totalMs) * 100, 0.5);
    return {
      startPct,
      widthPct: Math.min(widthPct, 100 - startPct),
      durationMs: duration,
      instant: false,
    };
  }
  return { startPct: Math.min((offset / totalMs) * 100, 100), widthPct: 0, durationMs: 0, instant: true };
}

function emptyState(title, subtitle) {
  const empty = make("div", "empty-state");
  empty.append(
    make("p", "empty-title", title),
    make("p", "empty", subtitle),
  );
  return empty;
}

function renderInspector() {
  for (const tab of elements.tabs) {
    const active = tab.dataset.tab === state.inspectorTab;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  }

  elements.inspectorContent.replaceChildren();
  const run = findRun(state.activeRunId);

  if (state.inspectorTab === "turns") {
    elements.inspectorContent.append(renderTurns());
    return;
  }
  if (state.inspectorTab === "eval") {
    elements.inspectorContent.append(renderEval());
    return;
  }

  if (!run) {
    elements.inspectorContent.append(make("p", "empty compact", "No run selected"));
    return;
  }
  const event = displayEvents(run.events).find((item) => item.event_id === state.activeEventId);

  if (state.inspectorTab === "json") {
    elements.inspectorContent.append(jsonView(event || run));
  } else {
    if (!event) {
      elements.inspectorContent.append(make("p", "empty compact", "No event selected"));
      return;
    }
    elements.inspectorContent.append(detailView(event));
  }
}

function renderTurns() {
  const group = sessionGroups().find((g) => g.key === state.activeSessionKey);
  if (!group) {
    return make("p", "empty compact", "Select a session to see its turns");
  }
  const list = make("div", "turn-list");
  for (const run of group.runs) {
    const card = make("button", `turn-card${run.run_id === state.activeRunId ? " active" : ""}`);
    card.type = "button";
    card.title = run.prompt || run.run_id;
    card.addEventListener("click", () => selectRun(run.run_id));
    const line1 = make("span", "turn-line");
    line1.append(
      make("span", `status-dot ${run.status}`),
      make("span", "turn-prompt", run.prompt || "Untitled run"),
    );
    const badge = evalBadge(run);
    if (badge) {
      const chip = make("span", `eval-badge ${badge.status}`);
      chip.textContent = badge.label;
      chip.title = `Eval ${badge.score != null ? badge.score.toFixed(2) : "–"} (${badge.passed}/${badge.total})`;
      line1.append(chip);
    }
    line1.append(make("span", "turn-time", formatClock(run.started_at)));
    card.append(line1);
    if (run.response_text) {
      card.append(make("span", "turn-response", run.response_text));
    }
    list.append(card);
  }
  return list;
}

function evalBadge(run) {
  const results = run.evalResults;
  if (!Array.isArray(results) || results.length === 0) {
    return null;
  }
  const statuses = results.map((result) => result.status);
  let status = "passed";
  if (statuses.includes("failed")) {
    status = "failed";
  } else if (statuses.includes("not_evaluated")) {
    status = "not_evaluated";
  }
  const passed = results.filter((result) => result.status === "passed").length;
  const scored = results.filter((result) => typeof result.score === "number");
  const score = scored.length
    ? scored.reduce((sum, result) => sum + result.score, 0) / scored.length
    : null;
  return { status, label: `${passed}/${results.length}`, score, passed, total: results.length };
}

function detailView(event) {
  const list = make("dl", "detail-list");
  for (const [label, value] of detailPairs(event)) {
    if (value === null || value === undefined || value === "") {
      continue;
    }
    const row = make("div", "detail-row");
    row.append(make("dt", "", label), make("dd", "", displayValue(value)));
    list.append(row);
  }
  return list;
}

function renderEval() {
  const run = findRun(state.activeRunId);
  if (!run) {
    return make("p", "empty compact", "Select a run to see its eval results");
  }
  const results = run.evalResults;
  if (!Array.isArray(results) || results.length === 0) {
    return make("p", "empty compact", "No eval results for this run");
  }
  const list = make("div", "eval-results");
  for (const result of results) {
    const card = make("div", "eval-case");
    const head = make("div", "eval-case-head");
    head.append(
      make("span", `status-dot ${result.status}`),
      make("span", "eval-case-id", result.case_id),
      make("span", "eval-case-score", result.score != null ? result.score.toFixed(2) : "–"),
    );
    card.append(head);
    for (const reason of result.failure_reasons || []) {
      card.append(make("div", "eval-reason", reason));
    }
    for (const grader of result.graders || []) {
      const row = make("div", "eval-grader");
      row.append(
        make("span", "eval-grader-key", grader.key),
        make("span", `eval-grader-status ${grader.status}`, grader.status),
        make("span", "eval-grader-reason", grader.reason || ""),
      );
      card.append(row);
    }
    list.append(card);
  }
  return list;
}

function detailPairs(event) {
  return [
    ["Type", event.type],
    ["Sequence", event.sequence],
    ["Created", event.created_at],
    ["Event ID", event.event_id],
    ["Call ID", event.call_id],
    ["Agent", event.agent_id],
    ["Session", event.session_id],
    ["Node", event.node_name],
    ["Parents", event.parent_ids],
    ["Model", event.model_name],
    ["Tool", event.tool_name],
    ["Duration", event.duration_ms === undefined ? null : formatDuration(event.duration_ms)],
    ["Input", event.tool_input],
    ["Output", event.tool_output],
    ["Usage", event.usage],
    ["Tool calls", event.tool_calls],
    ["Error", event.error_message || event.reason],
    ["Message", messageText(event.message)],
    ["Text", event.text],
    ["Chunks", event.delta_count],
  ];
}

function jsonView(value) {
  return make("pre", "json-view", JSON.stringify(value, null, 2));
}

function displayEvents(events) {
  const items = [];
  for (const event of Array.isArray(events) ? events : []) {
    if (event.type !== "text_delta") {
      items.push(event);
      continue;
    }
    const last = items.at(-1);
    if (last?.type === "text_stream") {
      last.text += event.text || "";
      last.delta_count += 1;
      last.source_events.push(event);
      continue;
    }
    items.push({
      ...event,
      type: "text_stream",
      event_id: `stream:${event.event_id}`,
      text: event.text || "",
      delta_count: 1,
      source_events: [event],
    });
  }
  return items;
}

function eventTitle(event) {
  const labels = {
    run_started: "Run started",
    message_created: "Message created",
    model_started: "Model started",
    model_finished: "Model completed",
    model_failed: "Model failed",
    tool_started: "Tool started",
    tool_finished: "Tool completed",
    tool_failed: "Tool failed",
    text_stream: "Response stream",
    run_finished: "Run completed",
    run_failed: "Run failed",
    run_cancelled: "Run cancelled",
  };
  return labels[event.type] || event.type || "Event";
}

function eventSubtitle(event) {
  if (event.type === "text_stream") {
    return `${event.delta_count} chunks / ${compactText(event.text)}`;
  }
  if (event.tool_name) {
    return `${event.tool_name}${event.call_id ? ` / ${event.call_id}` : ""}`;
  }
  if (event.model_name || event.call_id) {
    return [event.model_name, event.call_id].filter(Boolean).join(" / ");
  }
  if (event.error_message || event.reason) {
    return compactText(event.error_message || event.reason);
  }
  if (event.message) {
    return compactText(messageText(event.message));
  }
  return `#${String(numberValue(event.sequence)).padStart(3, "0")}`;
}

function eventGroup(event) {
  if (event.type?.includes("failed")) {
    return "error";
  }
  if (event.type?.startsWith("model_")) {
    return "model";
  }
  if (event.type?.startsWith("tool_")) {
    return "tool";
  }
  if (event.type === "text_stream") {
    return "stream";
  }
  if (event.type === "message_created") {
    return "message";
  }
  return "run";
}

function eventDepth(event) {
  return Array.isArray(event.parent_ids) ? event.parent_ids.length : 0;
}

function eventOffset(run, event) {
  const start = Date.parse(run.started_at);
  const current = Date.parse(event.created_at);
  if (!Number.isFinite(start) || !Number.isFinite(current)) {
    return `#${String(numberValue(event.sequence)).padStart(3, "0")}`;
  }
  return `+${((current - start) / 1000).toFixed(3)}s`;
}

// --- 状态 / 主题 ---

function setStatus(status, text) {
  elements.connectionStatus.dataset.state = status;
  elements.connectionStatus.textContent = text;
  elements.connectionStatus.title = text;
}

function currentTheme() {
  return document.documentElement.dataset.theme || "light";
}

function loadTheme() {
  try {
    const saved = localStorage.getItem(THEME_KEY);
    if (saved === "light" || saved === "dark") {
      return saved;
    }
  } catch {
    /* ignore */
  }
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem(THEME_KEY, theme);
  } catch {
    /* ignore */
  }
}

// --- 工具 ---

function normalizeRunRecord(run) {
  return {
    run_id: run.run_id,
    agent_id: run.agent_id || "unknown",
    user_id: run.user_id || "",
    session_id: run.session_id || "",
    prompt: run.prompt || "",
    status: run.status || "running",
    started_at: run.started_at || new Date().toISOString(),
    completed_at: run.completed_at || null,
    duration_ms: run.duration_ms ?? null,
    model_calls: run.model_calls ?? 0,
    tool_calls: run.tool_calls ?? 0,
    usage: run.usage || {},
    response_text: "",
    interruption_reason: null,
    summary: null,
    events: [],
    evalResults: null,
  };
}

function findRun(runId) {
  return runId ? state.runs.find((run) => run.run_id === runId) : null;
}

function runDuration(run) {
  const summaryDuration = run.summary?.duration_ms;
  if (summaryDuration !== undefined && summaryDuration !== null) {
    return summaryDuration;
  }
  if (run.duration_ms !== undefined && run.duration_ms !== null) {
    return run.duration_ms;
  }
  const start = Date.parse(run.started_at);
  const end = Date.parse(run.completed_at || new Date().toISOString());
  return Number.isFinite(start) && Number.isFinite(end) ? end - start : null;
}

function countEvents(run, type) {
  return run.events.filter((event) => event.type === type).length;
}

function messageText(message) {
  if (!message || !Array.isArray(message.parts)) {
    return "";
  }
  return message.parts
    .filter((part) => part?.type === "text" && typeof part.text === "string")
    .map((part) => part.text)
    .join("");
}

function displayValue(value) {
  return typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

function compactText(value) {
  return String(value || "").replace(/\s+/g, " ").trim().slice(0, 120);
}

function formatDuration(value) {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  const duration = Number(value);
  if (!Number.isFinite(duration)) {
    return "-";
  }
  if (duration >= 1000) {
    return `${(duration / 1000).toFixed(duration >= 10000 ? 1 : 2)}s`;
  }
  return `${duration.toFixed(duration >= 100 ? 0 : 1)}ms`;
}

function formatClock(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "--:--";
  }
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function formatDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "--";
  }
  const today = new Date();
  const sameDay = date.toDateString() === today.toDateString();
  return sameDay
    ? date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : date.toLocaleDateString([], { month: "short", day: "numeric" });
}

function formatNumber(value) {
  return new Intl.NumberFormat().format(numberValue(value));
}

function numberValue(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

function readableError(error) {
  return error instanceof Error ? error.message : String(error);
}

function readableConnectionError(error) {
  const message = readableError(error);
  if (message === "Failed to fetch") {
    return "API unreachable or blocked by CORS";
  }
  return message;
}

async function responseError(response) {
  try {
    const payload = await response.json();
    return payload.info || payload.detail || `Request failed with HTTP ${response.status}`;
  } catch {
    return `Request failed with HTTP ${response.status}`;
  }
}

function normalizeApiUrl(value) {
  const url = new URL(String(value).trim());
  if (!new Set(["http:", "https:"]).has(url.protocol) || !url.hostname) {
    throw new Error("API URL must use http:// or https://");
  }
  if (url.username || url.password || url.search || url.hash) {
    throw new Error("API URL must not contain credentials, query, or fragment");
  }
  return `${url.origin}${url.pathname.replace(/\/+$/, "")}`;
}

function make(tag, className = "", text = null) {
  const node = document.createElement(tag);
  if (className) {
    node.className = className;
  }
  if (text !== null) {
    node.textContent = text;
  }
  return node;
}
