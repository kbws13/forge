# Forge

Forge 是 Python Agent 服务的运行时 SDK 与 FastAPI 脚手架。MVP 聚焦项目生成、
模型与工具调用、结构化输出、运行控制、token 用量和 Trace 日志。

## 边界与版本

- [`kbws-forge-runtime`](packages/forge-runtime)：Agent、会话、Prompt、中间件、工具与类型化事件。
- [`kbws-forge-cli`](packages/forge-cli)：`forge init` 生成服务，`forge trace` 查看运行轨迹。
- CLI 2.0 生成的项目约束 `kbws-forge-runtime>=2.0.0,<3`。两个包独立安装和发布。
- 2.0 移除 Eval 引擎、CLI、API 和界面；普通单元、接口、集成及浏览器测试保留。
- 项目管理、人工审批、设备调度、业务验收和报告属于使用方，不进入 Forge。

已有 1.x 项目升级前阅读 [迁移说明](docs/migration-v2.md)；版本变化见 [CHANGELOG](CHANGELOG.md)。

## 快速开始

需要 Python 3.13+ 和 [uv](https://docs.astral.sh/uv/)。

```bash
pip install "kbws-forge-cli>=2,<3"
forge init my-agent -t service-agent
cd my-agent
uv sync
# 复制 .env.example 为 .env，设置 API_KEY 和 DEEPSEEK_* 配置
uv run uvicorn app.main:app --reload
```

另开终端运行 `forge trace --api-url http://127.0.0.1:8000/api/v1`。
`service-agent` 提供分层 FastAPI 服务、鉴权、日志、示例 Agent 和测试；
`base-agent` 仅提供最小 FastAPI Hello World，不包含 Trace API。
模型名和 API 地址由使用方配置，不能将兼容接口等同于已完成真实模型验证。

## Token 与 Trace

Trace 面板查看会话、逐轮对话、模型/工具事件、耗时、用量和原始 JSON。
服务端以 `run_id` 关联运行，通过 `/api/v1/traces` 查询。

- Trace 默认保存在 `logs/traces.json`，逐事件原子替换文件；记录有数量上限。
- 仅支持单进程写入；部署使用一个 worker，不让多个进程共享该文件。
- 重启后未完成的运行标为 `interrupted`，不会自动恢复或重放。
- 原子替换不等于 `fsync` 持久性；断电、磁盘故障和写入失败可能丢失记录。
- 用量区分已知、未知及部分已知；未知不能解释为零，部分用量不能解释为完整消耗。
- 保留供应商提供的 token 数据，不内置价格表、费用推算或计费平台。

Trace 可能包含输入、输出和工具参数，应按应用要求控制访问与保留周期。
运行轨迹持久化也不代表会话内存和业务任务能够恢复。

## 仓库与开发

`packages/forge-runtime/` 放 SDK；`packages/forge-cli/` 放生成器、模板和 Trace UI；
`docs/` 放迁移文档。根目录通过 uv workspace 管理依赖。

```bash
uv sync --all-packages --all-extras
uv run pytest packages/forge-runtime/tests
uv run pytest packages/forge-cli/tests
```

测试按以上顺序串行执行。普通测试使用 fake model；真实供应商测试默认跳过。
浏览器测试需 Node、npm 和 Chrome/Chromium，设置 `FORGE_E2E=1` 后运行
`uv run pytest packages/forge-cli/tests/test_e2e_trace_ui.py -v`。
真实 DeepSeek 调用和人工视觉验收需单独执行，不能由普通测试通过推断。

## License

MIT License
