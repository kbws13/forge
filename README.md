# Forge

> AI Agent 脚手架：一个用 Python 构建编码代理（coding agent）的 monorepo。

## 包含什么

| 包 | PyPI | 说明 |
| --- | --- | --- |
| [`packages/forge-runtime`](packages/forge-runtime) | [kbws-forge-runtime](https://pypi.org/project/kbws-forge-runtime/) | 框架无关的 agent 运行时：AgentRuntime、组件化 Prompt、agent 目录约定、workflow builders、工具/MCP/技能、类型化事件流 |
| [`packages/forge-cli`](packages/forge-cli) | [kbws-forge-cli](https://pypi.org/project/kbws-forge-cli/) | Vite 式交互脚手架：`forge init` 生成分层 FastAPI Agent 服务 |

## 快速开始

```bash
pip install kbws-forge-cli
forge init my-agent          # 交互式生成项目
cd my-agent
uv sync                      # 自动安装 kbws-forge-runtime
uv run uvicorn app.main:app --reload
```

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

## 设计要点

- **uv workspace 管理**：两个包各自独立发布 PyPI，开发期 workspace 内互链（editable）
- **SDK 框架无关**：`kbws-forge-runtime` 不绑定任何 Web 框架；FastAPI 层由 `forge-cli` 生成的模板承载
- **代码化 Prompt**：prompt 是 Python 组件（组合/复用/单测），不用配置文件
- **agent 目录约定**：一个 agent = 一个目录（agent.py + prompts.py + tools.py），自动发现注册

## 开发

```bash
uv sync --all-extras
uv run pytest packages/forge-runtime/tests
uv run pytest packages/forge-cli/tests
```

## License

MIT License
