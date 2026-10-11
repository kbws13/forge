"""Provider configuration must expose usage and avoid hidden SDK retries."""

from app.core.config import Settings
from app.providers.llm import build_model


def test_model_requests_stream_usage_and_disables_automatic_retries() -> None:
    settings = Settings(
        deepseek_api_key="test-key",
        deepseek_base_url="https://example.invalid/v1",
        deepseek_model="configured-model",
    )

    model = build_model(settings)

    assert model.stream_usage is True
    assert model.max_retries == 0
    assert model.model_name == "configured-model"
    assert model.openai_api_base == "https://example.invalid/v1"
