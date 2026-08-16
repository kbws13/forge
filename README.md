# Forge

> 自研 Agent 框架：运行时 SDK + 脚手架 CLI。企业里快速搭建、按场景定制 Agent 服务。

Forge 解决的是"从零搭一个 Agent 服务"的重复工作：架构分层、鉴权、日志、多环境配置、
Prompt 组件化、agent 组织方式……这些能力被封装成开箱即用的脚手架，业务团队专注写
自己的 agent 逻辑，而不是每次重造一套基础设施。

## 包含什么

| 包 | PyPI | 职责 |
| --- | --- | --- |
| [`packages/forge-runtime`](packages/forge-runtime) | [kbws-forge-runtime](https://pypi.org/project/kbws-forge-runtime/) | 运行时 SDK：AgentRuntime、组件化 Prompt、模型中间件、结构化输出、agent 目录约定、workflow builders、工具/MCP/技能、类型化事件流 |
| [`packages/forge-cli`](packages/forge-cli) | [kbws-forge-cli](https://pypi.org/project/kbws-forge-cli/) | 开发 CLI：`forge init` 生成完整分层服务，`forge trace` 在浏览器检查 Agent 运行轨迹 |

## 快速开始

```bash
pip install kbws-forge-cli
forge init my-agent          # 交互式生成项目（Vite 风格）
cd my-agent
uv sync                      # 自动安装 kbws-forge-runtime
uv run uvicorn app.main:app --reload
# 另开终端，在本地浏览器查看 Agent 运行轨迹（ADK/LangSmith 风格面板）
forge trace --api-url http://127.0.0.1:8000/api/v1
```

生成的即是可运行、可测试、可部署的服务骨架：业务聚合层（`agents/`）+ 技术分层
（`app/`），内置全局异常、统一响应、API Key 鉴权、多环境配置、日志持久化、分层测试，
并自带模型中间件与结构化输出的示例 agent。

## Trace 面板

`forge trace` 启动一个只监听 `127.0.0.1` 的浏览器面板，用于审查 Agent 执行过程，
界面结构参考 Google ADK 与 LangSmith：

- **会话列表**：服务端记录的所有会话（按最新活动排序，可过滤/删除）
- **Turns 面板**：会话内逐轮对话（状态/消息/回复），几十轮也能滚动审查
- **执行树**：选中一轮查看其完整执行流——Invocation 头（耗时/模型/工具/token 统计）、
  Chrome F12 式共享时间轴（刻度标尺 + 瀑布条 + 树形连接线）、事件级详情与原始 JSON
- **全量 trace**：任何客户端（curl / Yaak / 脚本）发起的 run 都会被服务端记录到
  `logs/traces.json`（重启不丢），面板自动连接 + 定时刷新即可看到，无需手动操作

### 评估与 CI 门禁

```bash
forge eval run smoke --fail-under 0.9 --report junit -o out/   # 跑评估 + 门禁 + JUnit 报告
forge eval run smoke --mode replay                             # 重打分已记录 run（零外部调用）
forge eval compare --baseline <eval_run_id> --live             # 基线 vs 候选，输出回归清单
forge eval dataset export smoke -o cases.jsonl                 # 数据集导出
forge eval dataset import cases.jsonl --name golden --agent <agent_id>
```

```bash
# 查看 trace 查询 API
curl -H "X-API-Key: <key>" http://127.0.0.1:8000/api/v1/traces
curl -H "X-API-Key: <key>" http://127.0.0.1:8000/api/v1/traces/<run_id>
```

## 设计理念

- **脚手架优先**：框架的价值在于"生成即用、按需定制"——`forge init` 产出完整骨架，业务代码（agent/prompt/tools）在自己的目录里演进，不碰框架层
- **代码化 Prompt**：prompt 是 Python 组件（`Message`/`Prompt`/`compose`），可组合、复用、单测，不用配置文件维护
- **agent 目录约定**：一个 agent = 一个目录（`agent.py` + `prompts.py` + `tools.py`），`load_agents` 自动发现注册——加 agent 不加代码
- **框架无关的运行时**：SDK 不绑定任何 Web 框架；HTTP 层由脚手架模板承载，换协议不换业务
- **场景可定制**：模板、prompt 组件、工具/MCP/技能、插件钩子都是扩展点，按企业场景自由组合

## 仓库结构

```
forge/
├── packages/
│   ├── forge-runtime/       # SDK：agent 运行时（发布到 PyPI）
│   └── forge-cli/           # CLI：脚手架生成器（发布到 PyPI）
├── pyproject.toml           # uv workspace 根
├── uv.lock
└── README.md
```

## 开发

```bash
uv sync --all-extras
uv run pytest packages/forge-runtime/tests
uv run pytest packages/forge-cli/tests

# Trace 面板浏览器 e2e（需 Chrome + Node，默认跳过）：
FORGE_E2E=1 uv run pytest packages/forge-cli/tests/test_e2e_trace_ui.py -v
```

## License

MIT License
