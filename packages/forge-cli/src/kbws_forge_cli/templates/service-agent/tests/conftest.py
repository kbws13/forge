"""Shared fixtures for the demo test suite."""

from __future__ import annotations

import os
from typing import Any

import pytest
from fastapi.testclient import TestClient
from kbws_forge_runtime import AgentRuntime
from kbws_forge_runtime.agent import load_agents
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from pydantic import SecretStr

API_KEY = "test-secret-key"

os.environ["APP_ENV"] = "test"
# app/main.py 模块级 create_app 会在 import 时构造 Settings，
# 注入假 key 保证 import 成功（测试不依赖任何 .env 文件）
os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")
os.environ.setdefault("API_KEY", API_KEY)

from app.core.config import Settings
from app.main import create_app


class BindableFakeChatModel(FakeListChatModel):
    """FakeListChatModel 不支持 bind_tools，这里补齐以便走完整的工具装配路径。"""

    def bind_tools(self, tools: Any, **kwargs: Any) -> BindableFakeChatModel:
        return self


@pytest.fixture(scope="session")
def settings() -> Settings:
    # 测试不依赖任何 .env 文件：用假 key；真实调用由 integration 测试单独控制
    return Settings(
        _env_file=None,
        deepseek_api_key=SecretStr("test-key"),
        api_key=API_KEY,
        log_level="WARNING",
    )


@pytest.fixture
async def client(settings: Settings):
    """TestClient with a fake-model runtime injected (no paid API calls).

    Uses the real ``load_agents`` discovery against the demo agents/ tree,
    but with a fake model factory so nothing is billed.
    """
    app = create_app(settings)
    with TestClient(app) as test_client:
        runtime = AgentRuntime(plugins=[])
        await load_agents(
            "agents",
            runtime,
            model_factory=lambda: BindableFakeChatModel(responses=["Hello from fake agent."]),
        )
        app.state.runtime = runtime
        yield test_client


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"X-API-Key": API_KEY}
