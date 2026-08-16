from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, cast

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langchain_core.prompts import BaseChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langchain_core.utils.function_calling import convert_to_openai_function
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, ValidationError

from kbws_forge_runtime.execution import ModelExecutor, ToolExecutor, current_run_context
from kbws_forge_runtime.middleware import ModelMiddleware
from kbws_forge_runtime.prompts import Prompt, render_instruction
from kbws_forge_runtime.workflow.state import WorkflowState

# 结构化输出的专用工具名
_OUTPUT_TOOL_NAME = "__forge_structured_output"


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
    middleware: Sequence[ModelMiddleware] = (),
    output_schema: type[BaseModel] | None = None,
) -> Any:
    """Build one chat agent graph, including a local tool loop when needed.

    ``instruction`` accepts a plain string (system message), a composable
    ``Prompt`` (code-first blocks with history/variable injection), or any
    langchain chat prompt template for full flexibility.

    ``middleware`` are model-level interceptors (deepagents-style):
    ``before_model`` / ``after_model`` / ``wrap_model_call`` run around every
    model call.

    ``output_schema`` is a pydantic model supplied by the caller. The model is
    asked to answer via a dedicated tool call, whose arguments are parsed into
    the schema and exposed as ``RunFinished.parsed`` / ``ChatResult.parsed``.
    """
    builder = StateGraph(WorkflowState)
    middlewares = tuple(middleware)

    bound_tools = list(tools)
    output_tool: dict[str, Any] | None = None
    if output_schema is not None:
        output_tool = convert_to_openai_function(output_schema)
        output_tool["name"] = _OUTPUT_TOOL_NAME
        bound_tools.append(output_tool)
    chat_model = model.bind_tools(bound_tools) if bound_tools else model

    async def invoke_model(state: WorkflowState, prompt: list[BaseMessage]) -> BaseMessage:
        for mw in middlewares:
            result = await mw.before_model(state, prompt)
            if result is not None:
                prompt = result

        async def _call(messages: list[BaseMessage]) -> BaseMessage:
            context = current_run_context()
            if context is None:
                return await chat_model.ainvoke(messages)
            return await ModelExecutor(context).ainvoke(lambda: chat_model.ainvoke(messages))

        handler = _call
        for mw in reversed(middlewares):
            previous = handler

            async def wrapped(
                messages: list[BaseMessage],
                middleware: ModelMiddleware = mw,
                next_handler: Any = previous,
            ) -> BaseMessage:
                return await middleware.wrap_model_call(messages, next_handler)

            handler = wrapped

        response = await handler(prompt)
        for mw in reversed(middlewares):
            result = await mw.after_model(state, response)
            if result is not None:
                response = result
        return response

    async def chat_node(state: WorkflowState, config: RunnableConfig) -> dict[str, Any]:
        call_variables = config.get("configurable", {}).get("variables") or {}
        prompt = render_instruction(
            instruction,
            history=list(state.get("messages", [])),
            outputs=state.get("outputs", {}),
            variables=call_variables,
        )

        response = await invoke_model(state, prompt)
        return {"messages": [response]}

    async def finalize(state: WorkflowState) -> dict[str, Any]:
        """Parse the structured-output tool call into the schema (one retry)."""
        assert output_schema is not None
        last = state.get("messages", [])[-1] if state.get("messages") else None
        args: dict[str, Any] | None = None
        if isinstance(last, AIMessage) and last.tool_calls:
            for tc in last.tool_calls:
                if tc.get("name") == _OUTPUT_TOOL_NAME:
                    args = tc.get("args", {})
                    break
        if args is None:
            return {}
        try:
            # 存 dict：pydantic 实例进 checkpointer 后无法可靠反序列化
            return {"parsed": output_schema.model_validate(args).model_dump()}
        except ValidationError:
            pass
        # 重试一次：把错误回注，让模型重新输出
        retry_prompt = [
            SystemMessage(
                content=(
                    f"你上一次的结构化输出无法解析，请修正后重新调用 "
                    f"{_OUTPUT_TOOL_NAME} 工具。解析错误：{args}"
                )
            ),
            last,
        ]
        retry = await invoke_model(state, retry_prompt)
        for tc in getattr(retry, "tool_calls", []) or []:
            if tc.get("name") == _OUTPUT_TOOL_NAME:
                try:
                    return {"parsed": output_schema.model_validate(tc.get("args", {})).model_dump()}
                except ValidationError:
                    pass
        return {}

    builder.add_node("chat", cast(Any, chat_node))
    builder.add_edge(START, "chat")
    if bound_tools:

        async def governed_tool_call(request: Any, handler: Any) -> Any:
            context = current_run_context()
            if context is None:
                return await handler(request)
            tool_call = request.tool_call
            return await ToolExecutor(context).ainvoke(
                tool_call["name"],
                tool_call.get("args"),
                lambda: handler(request),
            )

        builder.add_node(
            "tools",
            ToolNode(list(tools), awrap_tool_call=governed_tool_call),
        )

        def route(state: WorkflowState) -> str:
            last = state.get("messages", [])[-1] if state.get("messages") else None
            if isinstance(last, AIMessage) and last.tool_calls:
                names = {tc.get("name") for tc in last.tool_calls}
                # 只请求结构化输出 -> 直接收尾；请求了真实工具 -> 进工具节点
                if output_tool is not None and names and names <= {_OUTPUT_TOOL_NAME}:
                    return "finalize" if output_schema is not None else END
                if tools:
                    return "tools"
            return "finalize" if output_schema is not None else END

        if output_schema is not None:
            builder.add_node("finalize", cast(Any, finalize))
            builder.add_edge("finalize", END)
            builder.add_conditional_edges("chat", route, ["finalize", "tools"])
        else:
            builder.add_conditional_edges("chat", route, [END, "tools"])
        if tools:
            builder.add_edge("tools", "chat")
    else:
        builder.add_edge("chat", END)
    compiled = _compile(builder, checkpointer)
    if output_schema is not None:
        # 动态属性：让 GraphAgent 能把 state 里的 dict 还原回 pydantic 实例
        compiled.forge_output_schema = output_schema  # type: ignore[attr-defined]
    return compiled
