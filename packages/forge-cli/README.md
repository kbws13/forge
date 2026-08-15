# kbws-forge-cli

Forge 的 CLI 与脚手架生成器（PyPI 发布名：`kbws-forge-cli`），用于创建编码代理项目。

## 安装

```bash
pip install kbws-forge-cli
```

## 用法

```bash
forge init my-agent                # 默认模板：service-agent（完整分层服务）
forge init my-hello -t base-agent  # 可选：最小 FastAPI HelloWorld
cd my-agent
uv sync
uv run uvicorn app.main:app --reload
```

> `--template/-t` 保留用于以后多模板选择（届时也会支持交互式选择）；当前默认即 `service-agent`。

## 模板

| 模板 | 说明 |
| --- | --- |
| `base-agent` | 最小 FastAPI HelloWorld，快速起步 |
| `service-agent` | 完整分层服务：业务聚合（`agents/`）+ 技术分层（`app/`），含全局异常、统一响应、API Key 鉴权、多环境配置、日志持久化、分层测试；依赖已发布的 `kbws-forge-runtime` |

`service-agent` 生成的项目结构：

```
my-service/
├── agents/<module_name>/     # 业务聚合：agent.py + prompts.py + tools.py
├── app/                      # 技术分层：core / api / schemas / services / providers
├── tests/                    # unit / api / integration（真实 provider 开关控制）
├── scripts/run.sh
└── .env.example
```

## 开发

```bash
uv sync
uv run pytest packages/forge-cli/tests
```

## License

MIT License
