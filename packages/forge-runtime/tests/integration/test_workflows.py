import pytest
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from kbws_forge_runtime.workflow import (
    AgentStep,
    build_chat_graph,
    build_loop,
    build_parallel,
    build_sequence,
)

pytestmark = pytest.mark.real_provider


async def test_sequence_passes_real_output_into_later_prompt(real_model: ChatOpenAI) -> None:
    writer = build_chat_graph(
        real_model,
        instruction="Reply with exactly DRAFT_OK and nothing else.",
    )
    reviewer = build_chat_graph(
        real_model,
        instruction=(
            "If the supplied draft contains DRAFT_OK, reply exactly REVIEW_OK. "
            "Otherwise reply REVIEW_BAD.\nDraft:\n{generated_code}"
        ),
    )
    graph = build_sequence(
        [
            AgentStep("writer", writer, output_key="generated_code"),
            AgentStep("reviewer", reviewer, output_key="review_comments"),
        ]
    )

    result = await graph.ainvoke({"messages": [HumanMessage(content="Create a draft.")]})

    assert "DRAFT_OK" in result["outputs"]["generated_code"]
    assert "REVIEW_OK" in result["outputs"]["review_comments"]


async def test_parallel_agents_run_real_models_and_keep_named_outputs(
    real_model: ChatOpenAI,
) -> None:
    product = build_chat_graph(
        real_model,
        instruction="Reply with exactly PRODUCT_OK and nothing else.",
    )
    engineering = build_chat_graph(
        real_model,
        instruction="Reply with exactly ENGINEERING_OK and nothing else.",
    )
    graph = build_parallel(
        [
            AgentStep("product", product, output_key="product_view"),
            AgentStep("engineering", engineering, output_key="engineering_view"),
        ]
    )

    result = await graph.ainvoke({"messages": [HumanMessage(content="Analyze this topic.")]})

    assert "PRODUCT_OK" in result["outputs"]["product_view"]
    assert "ENGINEERING_OK" in result["outputs"]["engineering_view"]
    assert "product_view" in result["messages"][-1].content
    assert "engineering_view" in result["messages"][-1].content


async def test_loop_runs_real_agent_for_the_configured_round_count(
    real_model: ChatOpenAI,
) -> None:
    refine = build_chat_graph(
        real_model,
        instruction="Reply with exactly LOOP_OK and nothing else.",
    )
    graph = build_loop(
        [AgentStep("refine", refine, output_key="draft")],
        max_rounds=2,
    )

    result = await graph.ainvoke({"messages": [HumanMessage(content="Refine this.")]})

    assert result["round"] == 2
    assert "LOOP_OK" in result["outputs"]["draft"]


async def test_loop_stops_from_real_agent_output(real_model: ChatOpenAI) -> None:
    refine = build_chat_graph(
        real_model,
        instruction="Reply with exactly STOP_OK and nothing else.",
    )
    graph = build_loop(
        [AgentStep("refine", refine, output_key="draft")],
        max_rounds=5,
        stop_when=lambda state: "STOP_OK" in state.get("outputs", {}).get("draft", ""),
    )

    result = await graph.ainvoke({"messages": [HumanMessage(content="Finish this.")]})

    assert result["round"] == 1
    assert "STOP_OK" in result["outputs"]["draft"]
