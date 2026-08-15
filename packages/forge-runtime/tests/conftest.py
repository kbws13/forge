from collections.abc import Callable

import pytest
from langchain_openai import ChatOpenAI
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProviderSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    deepseek_api_key: SecretStr | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    run_real_provider_tests: bool = False


@pytest.fixture(scope="session")
def provider_settings() -> ProviderSettings:
    settings = ProviderSettings()
    if not settings.run_real_provider_tests:
        pytest.skip("set RUN_REAL_PROVIDER_TESTS=1 to call the real provider")
    if settings.deepseek_api_key is None:
        pytest.skip("DEEPSEEK_API_KEY is not set")
    return settings


@pytest.fixture
def real_model_factory(
    provider_settings: ProviderSettings,
) -> Callable[..., ChatOpenAI]:
    def create(*, model: str | None = None, max_tokens: int = 300) -> ChatOpenAI:
        return ChatOpenAI(
            api_key=provider_settings.deepseek_api_key,
            base_url=provider_settings.deepseek_base_url,
            model=model or provider_settings.deepseek_model,
            temperature=0,
            max_tokens=max_tokens,
            max_retries=1,
            timeout=30,
        )

    return create


@pytest.fixture
def real_model(real_model_factory: Callable[..., ChatOpenAI]) -> ChatOpenAI:
    return real_model_factory()
