# kbws-forge-cli

Forge 的 CLI 与脚手架生成器（PyPI 发布名：`kbws-forge-cli`），用于创建编码代理项目。

## 安装

```bash
pip install kbws-forge-cli
```

## 用法

```bash
forge init my-agent
cd my-agent
uv sync
uv run fastapi dev
```

生成的 `my-agent` 是一个基于 FastAPI 的最小后端，访问 http://127.0.0.1:8000 可看到 `{"message": "Hello World"}`。

## 开发

```bash
uv sync
uv run pytest packages/forge-cli/tests
```

## License

MIT License
