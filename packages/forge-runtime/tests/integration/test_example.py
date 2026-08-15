import pytest

from tests.fixtures.java_parity_agent.agent_config import build_runtime
from tests.fixtures.java_parity_agent.settings import Settings

pytestmark = pytest.mark.real_provider


async def test_example_registers_all_agent_shapes_and_calls_real_provider(
    provider_settings,
) -> None:
    runtime = build_runtime(
        Settings(
            deepseek_api_key=provider_settings.deepseek_api_key,
            deepseek_base_url=provider_settings.deepseek_base_url,
            deepseek_model=provider_settings.deepseek_model,
        )
    )

    assert [agent.agent_id for agent in runtime.list_agents()] == [
        "assistant",
        "code-pipeline",
        "research-pipeline",
        "iterative-writer",
    ]

    result = await runtime.chat(
        "assistant",
        "example-test",
        "Reply with exactly EXAMPLE_OK and do not call any tool.",
    )
    assert "EXAMPLE_OK" in result.content
