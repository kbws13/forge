from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, cast

from langchain_core.messages import AIMessage
from langchain_core.prompts import BaseChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from kbws_forge_runtime.prompts import Prompt, render_instruction
from kbws_forge_runtime.workflow.state import WorkflowState


@dataclass(frozen=True, slots=True)
class AgentStep:
    name: str
    graph: Any
    output_key: str | None = None


async def _run_step(
    step: AgentStep, state: WorkflowState, config: RunnableConfig
) -> dict[str, Any]:
    result = await step.graph.ainvoke(
        {
            "messages": state.get("messages", []),
            "outputs": state.get("outputs", {}),
            "round": state.get("round", 0),
            "stop": state.get("stop", False),
        },
        config=config,
    )
    messages = result.get("messages", [])
    last = messages[-1] if messages else None
    text = getattr(last, "content", "") if last is not None else ""
    if not isinstance(text, str):
        text = str(text)
    outputs = dict(result.get("outputs", {}))
    outputs[step.output_key or step.name] = text
    update: dict[str, Any] = {
        "messages": [AIMessage(content=text)] if text else [],
        "outputs": outputs,
    }
    if result.get("stop"):
        update["stop"] = True
    return update


def _step_node(step: AgentStep) -> Callable[[WorkflowState, RunnableConfig], Any]:
    async def run(state: WorkflowState, config: RunnableConfig) -> dict[str, Any]:
        return await _run_step(step, state, config)

    return run


def _compile(builder: StateGraph, checkpointer: Any = None) -> Any:
    """Compile a graph.

    ``checkpointer=None`` uses the SDK default (in-memory session memory) so
    conversation history survives across calls in the same session. Pass your
    own langgraph saver to persist elsewhere.
    """
    if checkpointer is None:
        checkpointer = InMemorySaver()
    return builder.compile(checkpointer=checkpointer)


def build_sequence(steps: Sequence[AgentStep], *, checkpointer: Any = None) -> Any:
    """Run steps one after another, feeding each step's outputs into the next."""
    if not steps:
        raise ValueError("sequence needs at least one step")
    # noinspection PyTypeChecker
    builder = StateGraph(WorkflowState)
    for step in steps:
        # langgraph 1.x StateNode 存根对双参数节点误报，运行时注入 config 正常
        builder.add_node(step.name, cast(Any, _step_node(step)))
    builder.add_edge(START, steps[0].name)
    for current, following in zip(steps, steps[1:], strict=False):
        builder.add_edge(current.name, following.name)
    builder.add_edge(steps[-1].name, END)
    return _compile(builder, checkpointer)

def build_parallel(steps: Sequence[AgentStep], *, checkpointer: Any = None) -> Any:
    if not steps:
        raise ValueError("parallel needs at least one step")
    builder = StateGraph(WorkflowState)

    async def join(state: WorkflowState) -> dict[str, Any]:
        outputs = state.get("outputs", {})
        keys = [step.output_key or step.name for step in steps]
        text = "\n".join(f"{key}: {outputs.get(key, '')}" for key in keys)
        return {"messages": [AIMessage(content=text)]}

    builder.add_node("join", join)
    for step in steps:
        # langgraph 1.x StateNode 存根对双参数节点误报，运行时注入 config 正常
        builder.add_node(step.name, cast(Any, _step_node(step)))
        builder.add_edge(START, step.name)
        builder.add_edge(step.name, "join")
    builder.add_edge("join", END)
    return _compile(builder, checkpointer)

def build_loop(
    steps: Sequence[AgentStep],
    *,
    max_rounds: int = 3,
    stop_when: Callable[[WorkflowState], bool] | None = None,
    checkpointer: Any = None,
) -> Any:
    if not steps:
        raise ValueError("loop needs at least one step")
    if max_rounds < 1:
        raise ValueError("max_rounds must be positive")
    builder = StateGraph(WorkflowState)
    for step in steps:
        # langgraph 1.x StateNode 存根对双参数节点误报，运行时注入 config 正常
        builder.add_node(step.name, cast(Any, _step_node(step)))

    async def round_end(state: WorkflowState) -> dict[str, Any]:
        return {"round": state.get("round", 0) + 1}

    builder.add_node("round_end", round_end)
    builder.add_edge(START, steps[0].name)
    for current, following in zip(steps, steps[1:], strict=False):
        builder.add_edge(current.name, following.name)
    builder.add_edge(steps[-1].name, "round_end")

    def next_round(state: WorkflowState) -> str:
        should_stop = stop_when(state) if stop_when is not None else state.get("stop", False)
        if should_stop or state.get("round", 0) >= max_rounds:
            return END
        return steps[0].name

    builder.add_conditional_edges("round_end", next_round, [END, steps[0].name])
    return _compile(builder, checkpointer)


def build_chat_graph(
    model: Any,
    *,
    instruction: str | Prompt | BaseChatPromptTemplate,
    tools: Sequence[Any] = (),
    checkpointer: Any = None,
) -> Any:
    """Build one chat agent graph, including a local tool loop when needed.

    ``instruction`` accepts a plain string (system message), a composable
    ``Prompt`` (code-first blocks with history/variable injection), or any
    langchain chat prompt template for full flexibility.
    """
    builder = StateGraph(WorkflowState)
    chat_model = model.bind_tools(list(tools)) if tools else model

    async def chat_node(state: WorkflowState, config: RunnableConfig) -> dict[str, Any]:
        call_variables = config.get("configurable", {}).get("variables") or {}
        prompt = render_instruction(
            instruction,
            history=list(state.get("messages", [])),
            outputs=state.get("outputs", {}),
            variables=call_variables,
        )
        response = await chat_model.ainvoke(prompt)
        return {"messages": [response]}

    builder.add_node("chat", cast(Any, chat_node))
    builder.add_edge(START, "chat")
    if tools:
        builder.add_node("tools", ToolNode(list(tools)))
        builder.add_conditional_edges("chat", tools_condition, ["tools", END])
        builder.add_edge("tools", "chat")
    else:
        builder.add_edge("chat", END)
    return _compile(builder, checkpointer)
