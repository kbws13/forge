from __future__ import annotations

from pathlib import Path

from kbws_forge_runtime import RunPolicy, ToolPolicy
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App configuration.

    Load order (later wins): ``.env`` -> ``.env.{APP_ENV}`` -> real env vars.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- environment ---
    app_env: str = "dev"
    debug: bool = False

    # --- security ---
    # 服务自身的 API Key（X-API-Key 或 Bearer 头）。为空则鉴权关闭（仅建议本地调试）。
    api_key: str = ""

    # --- logging ---
    log_dir: Path = Path("logs")
    log_level: str = "INFO"

    # --- agents ---
    # 业务聚合层根目录：一个子目录 = 一个 agent（见 agents/assistant/ 示例）
    agents_dir: str = "agents"

    # --- run policy ---
    run_timeout_seconds: float | None = Field(default=None, gt=0)
    run_max_model_calls: int | None = Field(default=None, ge=1)
    run_max_tool_calls: int | None = Field(default=None, ge=1)
    run_max_total_tokens: int | None = Field(default=None, ge=1)
    run_max_cost_usd: float | None = Field(default=None, gt=0)
    run_max_concurrency: int | None = Field(default=None, ge=1)
    run_model_retries: int = Field(default=0, ge=0)
    run_tool_retries: int = Field(default=0, ge=0)
    run_retryable_tools: frozenset[str] = Field(default_factory=frozenset)
    run_retry_backoff_seconds: float = Field(default=0, ge=0)

    # --- model provider ---
    deepseek_api_key: SecretStr
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    def build_run_policy(self) -> RunPolicy:
        return RunPolicy(
            timeout_seconds=self.run_timeout_seconds,
            max_model_calls=self.run_max_model_calls,
            max_tool_calls=self.run_max_tool_calls,
            max_total_tokens=self.run_max_total_tokens,
            max_cost_usd=self.run_max_cost_usd,
            max_concurrency=self.run_max_concurrency,
            model_retries=self.run_model_retries,
            tool_retries=self.run_tool_retries,
            retry_backoff_seconds=self.run_retry_backoff_seconds,
            tool_policy=ToolPolicy(retryable_tools=self.run_retryable_tools),
        )

    @classmethod
    def load(cls, env_file: str | None = None) -> Settings:
        """Build settings for a specific environment file.

        ``APP_ENV`` selects ``.env.{APP_ENV}`` on top of the base ``.env``.
        Tests can pass an explicit file instead.
        """
        base = cls.model_config.get("env_file", ".env")
        files = [base] if isinstance(base, str) else list(base)
        if env_file:
            files.append(env_file)
        else:
            files.append(f".env.{cls._env_name()}")
        return cls(_env_file=files)

    @staticmethod
    def _env_name() -> str:
        import os

        return os.environ.get("APP_ENV", "dev")
