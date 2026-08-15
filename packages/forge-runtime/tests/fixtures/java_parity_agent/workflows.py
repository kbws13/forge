from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from kbws_forge_runtime.workflow import (
    AgentStep,
    build_chat_graph,
    build_loop,
    build_parallel,
    build_sequence,
)


def build_assistant(model: Any, tools: list[Any]) -> Any:
    return build_chat_graph(
        model,
        instruction=(
            "You are a practical assistant. Answer clearly and use a tool only when it helps. "
            "Use list_skills and read_skill_file when a task matches an available skill."
        ),
        tools=tools,
        checkpointer=InMemorySaver(),
    )


def build_code_pipeline(model: Any) -> Any:
    writer = build_chat_graph(
        model,
        instruction="Write code for the user's request. Return only the code.",
    )
    reviewer = build_chat_graph(
        model,
        instruction="Review this code and list concrete problems:\n{generated_code}",
    )
    refactorer = build_chat_graph(
        model,
        instruction=(
            "Refactor the code using the review. Return only the final code.\n"
            "Code:\n{generated_code}\nReview:\n{review_comments}"
        ),
    )
    return build_sequence(
        [
            AgentStep("writer", writer, output_key="generated_code"),
            AgentStep("reviewer", reviewer, output_key="review_comments"),
            AgentStep("refactorer", refactorer, output_key="refactored_code"),
        ],
        checkpointer=InMemorySaver(),
    )


def build_research_pipeline(model: Any) -> Any:
    product = build_chat_graph(
        model,
        instruction="Analyze the user's topic from a product perspective in 3 short points.",
    )
    engineering = build_chat_graph(
        model,
        instruction="Analyze the user's topic from an engineering perspective in 3 short points.",
    )
    research = build_parallel(
        [
            AgentStep("product", product, output_key="product_view"),
            AgentStep("engineering", engineering, output_key="engineering_view"),
        ]
    )
    summary = build_chat_graph(
        model,
        instruction=(
            "Merge the two analyses without adding unsupported facts.\n"
            "Product:\n{product_view}\nEngineering:\n{engineering_view}"
        ),
    )
    return build_sequence(
        [
            AgentStep("research", research),
            AgentStep("summary", summary, output_key="final_report"),
        ],
        checkpointer=InMemorySaver(),
    )


def build_iterative_writer(model: Any) -> Any:
    writer = build_chat_graph(
        model,
        instruction="Write a concise first draft for the user's request.",
    )
    critic = build_chat_graph(
        model,
        instruction="Give one concrete improvement for this draft:\n{draft}",
    )
    refiner = build_chat_graph(
        model,
        instruction="Rewrite the draft using the critique.\nDraft:\n{draft}\nCritique:\n{critique}",
    )
    refinement_loop = build_loop(
        [
            AgentStep("critic", critic, output_key="critique"),
            AgentStep("refiner", refiner, output_key="draft"),
        ],
        max_rounds=2,
    )
    return build_sequence(
        [
            AgentStep("first_draft", writer, output_key="draft"),
            AgentStep("refinement_loop", refinement_loop),
        ],
        checkpointer=InMemorySaver(),
    )
