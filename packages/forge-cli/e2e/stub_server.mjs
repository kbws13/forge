// Deterministic stub of the Forge agent service used by the Trace UI e2e.
// Serves a canned agent list, records every streamed run, exposes the trace
// query API (/traces), and seeds one "foreign" run that no UI client created —
// proving the trace panel shows runs from any source.
import http from "node:http";

const AGENTS = [
  { agent_id: "test_agent", name: "Test Agent", description: "Canned stub agent." },
];

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function cors(res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, X-API-Key");
}

function sendJson(res, status, payload) {
  cors(res);
  res.setHeader("Content-Type", "application/json");
  res.writeHead(status);
  res.end(JSON.stringify(payload));
}

function readBody(req) {
  return new Promise((resolve) => {
    let body = "";
    req.on("data", (chunk) => {
      body += chunk;
    });
    req.on("end", () => {
      try {
        resolve(body ? JSON.parse(body) : {});
      } catch {
        resolve({});
      }
    });
  });
}

function eventFrame(event, data) {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

function makeRun(seed, prompt = "现在几点？", user = "foreign") {
  const start = Date.now();
  const events = [];
  const base = {
    run_id: `stub-run-${seed}`,
    agent_id: "test_agent",
    session_id: `session-${user}`,
  };
  const at = (offset) => new Date(start + offset).toISOString();
  const usage = (input, output) => ({
    input_tokens: input,
    output_tokens: output,
    total_tokens: input + output,
    cost_usd: null,
  });
  let sequence = 0;
  const push = (type, extra, event = type, offset = 0) => {
    sequence += 1;
    events.push({ ...base, type, sequence, created_at: at(offset), ...extra });
  };

  push("run_started", { policy: { timeout_seconds: null, max_model_calls: null } }, "run_started", 0);
  push(
    "message_created",
    { message: { role: "user", parts: [{ type: "text", text: "现在几点？" }] } },
    "message_created",
    5,
  );
  push("model_started", { call_id: `${seed}-c1`, model_name: "StubModel", node_name: "chat" }, "model_started", 10);
  push(
    "model_finished",
    {
      call_id: `${seed}-c1`,
      model_name: "StubModel",
      node_name: "chat",
      duration_ms: 180,
      usage: usage(355, 27),
      tool_calls: [{ name: "current_time", args: {}, id: "tool-call-1", type: "tool_call" }],
    },
    "model_finished",
    195,
  );
  push("tool_started", { tool_name: "current_time", tool_input: {}, call_id: "tool-call-1", node_name: "tools" }, "tool_started", 200);
  push(
    "tool_finished",
    { tool_name: "current_time", tool_output: "2026-08-16T00:00:00+00:00", call_id: "tool-call-1", node_name: "tools", duration_ms: 0.7 },
    "tool_finished",
    201,
  );
  push("model_started", { call_id: `${seed}-c2`, model_name: "StubModel", node_name: "chat" }, "model_started", 215);
  for (const chunk of ["当前", "UTC", "时间是 00:00:00。"]) {
    push("text_delta", { text: chunk, node_name: "chat" }, "text_delta", 230);
  }
  push(
    "model_finished",
    {
      call_id: `${seed}-c2`,
      model_name: "StubModel",
      node_name: "chat",
      duration_ms: 150,
      usage: usage(413, 20),
      tool_calls: [],
    },
    "model_finished",
    330,
  );
  const finalMessage = { role: "assistant", parts: [{ type: "text", text: "当前 UTC 时间是 00:00:00。" }] };
  push("message_created", { message: finalMessage }, "message_created", 340);
  push(
    "run_finished",
    {
      message: finalMessage,
      parsed: null,
      duration_ms: 350,
      model_calls: 2,
      tool_calls: 1,
      usage: usage(768, 47),
    },
    "run_finished",
    350,
  );

  return {
    run_id: base.run_id,
    agent_id: base.agent_id,
    session_id: base.session_id,
    prompt,
    status: "finished",
    started_at: at(0),
    completed_at: at(350),
    duration_ms: 350,
    model_calls: 2,
    tool_calls: 1,
    usage: usage(768, 47),
    events,
  };
}

function summaryOf(run) {
  const { events: _events, ...summary } = run;
  return summary;
}

export function startStubService() {
  return new Promise((resolve) => {
    const runs = new Map();
    const order = [];
    const addRun = (run) => {
      runs.set(run.run_id, run);
      order.push(run.run_id);
    };

    // 预置一条"外部来源"的 run：不是本 UI 创建的，模拟 curl/Yaak 等其它客户端
    addRun(makeRun("foreign", "现在几点？", "foreign"));

    const server = http.createServer(async (req, res) => {
      const url = new URL(req.url, "http://127.0.0.1");
      if (req.method === "OPTIONS") {
        cors(res);
        res.writeHead(204);
        res.end();
        return;
      }

      if (url.pathname === "/api/v1/health") {
        sendJson(res, 200, { code: 0, info: "ok", data: { status: "ok" } });
        return;
      }
      if (url.pathname === "/api/v1/agents") {
        sendJson(res, 200, { code: 0, info: "ok", data: AGENTS });
        return;
      }
      if (url.pathname === "/api/v1/chat_stream") {
        cors(res);
        res.setHeader("Content-Type", "text/event-stream");
        res.setHeader("Cache-Control", "no-cache");
        res.writeHead(200);
        const body = await readBody(req);
        const run = makeRun(`ui-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`, body.message || "", body.user_id || "ui");
        for (const event of run.events) {
          res.write(eventFrame(event.type, event));
          await sleep(20);
        }
        addRun(run);
        res.end();
        return;
      }

      // /api/v1/traces 与 /api/v1/traces/{run_id}
      const tracesPrefix = "/api/v1/traces";
      if (url.pathname === tracesPrefix && req.method === "GET") {
        const limit = Number(url.searchParams.get("limit") || 100);
        const list = [...order].reverse().slice(0, limit).map((id) => summaryOf(runs.get(id)));
        sendJson(res, 200, { code: 0, info: "ok", data: list });
        return;
      }
      if (url.pathname === tracesPrefix && req.method === "DELETE") {
        runs.clear();
        order.length = 0;
        sendJson(res, 200, { code: 0, info: "ok", data: null });
        return;
      }
      const detailMatch = url.pathname.match(/^\/api\/v1\/traces\/([^/]+)$/);
      if (detailMatch) {
        const run = runs.get(decodeURIComponent(detailMatch[1]));
        if (!run) {
          sendJson(res, 404, { code: 40400, info: "trace not found", data: null });
          return;
        }
        if (req.method === "GET") {
          sendJson(res, 200, { code: 0, info: "ok", data: run });
          return;
        }
        if (req.method === "DELETE") {
          runs.delete(run.run_id);
          order.splice(order.indexOf(run.run_id), 1);
          sendJson(res, 200, { code: 0, info: "ok", data: null });
          return;
        }
      }
      sendJson(res, 404, { code: 40400, info: "not found", data: null });
    });
    server.listen(0, "127.0.0.1", () => {
      resolve({
        port: server.address().port,
        close: () => server.close(),
      });
    });
  });
}
