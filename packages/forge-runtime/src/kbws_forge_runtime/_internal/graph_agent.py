from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from time import monotonic
from typing import Any

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage

from kbws_forge_runtime.execution import (
    RunContext,
    default_usage_resolver,
)
from kbws_forge_runtime.models import (
    AgentInfo,
    ChatMessage,
    FilePart,
    InlineDataPart,
    MessageCreated,
    ModelFailed,
    ModelFinished,
    ModelStarted,
    RunFinished,
    TextDelta,
    ToolFailed,
    ToolFinished,
    ToolStarted,
)
from kbws_forge_runtime.workflow.graph import ChatGraph


def _part_block(part: Any) -> dict[str, Any]:
    if hasattr(part, "text"):
        return {"type": "text", "text": part.text}
    if isinstance(part, FilePart):
        block_type = "image" if part.mime_type.startswith("image/") else "file"
        return {
            "type": block_type,
            "source_type": "url",
            "url": part.uri,
            "mime_type": part.mime_type,
        }
    if isinstance(part, InlineDataPart):
        block_type = "image" if part.mime_type.startswith("image/") else "file"
        return {
            "type": block_type,
            "source_type": "base64",
            "data": base64.b64encode(part.data).decode("ascii"),
            "mime_type": part.mime_type,
        }
    raise TypeError(f"unsupported content part: {type(part).__name__}")


def to_langchain_message(message: ChatMessage) -> HumanMessage:
    if all(hasattr(part, "text") for part in message.parts):
        content: str | list[str | dict[Any, Any]] = message.text
    else:
        content = [_part_block(part) for part in message.parts]
    return HumanMessage(content=content)


def _text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, str):
                chunks.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                chunks.append(item["text"])
        return "".join(chunks)
    return str(content)


def _last_message(values: dict[str, Any]) -> AnyMessage | None:
    messages = values.get("messages", [])
    for message in reversed(messages):
        if isinstance(message, AIMessage) or getattr(message, "type", None) == "ai":
            return message
    return messages[-1] if messages else None


@dataclass(slots=True)
class GraphAgent:
    info: AgentInfo
    graph: ChatGraph

    async def stream(
        self,
        message: ChatMessage,
        *,
        run_id: str,
        session_id: str,
        variables: dict[str, Any] | None = None,
        run_context: RunContext | None = None,
    ) -> AsyncIterator[
        TextDelta
        | ModelStarted
        | ModelFinished
        | ModelFailed
        | ToolStarted
        | ToolFinished
        | ToolFailed
        | MessageCreated
        | RunFinished
    ]:
        config = {
            "configurable": {
                "thread_id": session_id,
                "variables": variables or {},
            },
            "metadata": {
                "run_id": run_id,
                "agent_id": self.info.agent_id,
                "session_id": session_id,
            },
        }
        final_values: dict[str, Any] | None = None
        input_state = {"messages": [to_langchain_message(message)]}
        action_started_at: dict[str, float] = {}

        def event_fields() -> dict[str, Any]:
            return {"sequence": run_context.next_sequence() if run_context is not None else 0}

        def action_fields(event: dict[str, Any]) -> dict[str, Any]:
            metadata = event.get("metadata", {})
            return {
                "call_id": str(event.get("run_id", "")),
                "parent_ids": tuple(str(value) for value in event.get("parent_ids", ())),
                "node_name": metadata.get("langgraph_node"),
            }

        def duration_ms(call_id: str) -> float | None:
            started_at = action_started_at.pop(call_id, None)
            if started_at is None:
                return None
            return (monotonic() - started_at) * 1000

        async for event in self.graph.astream_events(input_state, config=config, version="v2"):
            event_name = event.get("event")
            data = event.get("data", {})

            def common_fields() -> dict[str, Any]:
                return {
                    "run_id": run_id,
                    "agent_id": self.info.agent_id,
                    "session_id": session_id,
                    **event_fields(),
                }

            if event_name == "on_chat_model_start":
                fields = action_fields(event)
                action_started_at[fields["call_id"]] = monotonic()
                yield ModelStarted(
                    **common_fields(),
                    **fields,
                    model_name=event.get("name"),
                )
            elif event_name == "on_chat_model_stream":
                text = _text_from_content(getattr(data.get("chunk"), "content", ""))
                if text:
                    yield TextDelta(
                        **common_fields(),
                        text=text,
                        node_name=event.get("metadata", {}).get("langgraph_node"),
                    )
            elif event_name == "on_chat_model_end":
                fields = action_fields(event)
                output = data.get("output")
                usage_resolver = (
                    run_context.usage_resolver
                    if run_context is not None
                    else default_usage_resolver
                )
                usage = usage_resolver(output)
                yield ModelFinished(
                    **common_fields(),
                    **fields,
                    model_name=event.get("name"),
                    duration_ms=duration_ms(fields["call_id"]),
                    usage=usage,
                    tool_calls=tuple(getattr(output, "tool_calls", ()) or ()),
                )
            elif event_name == "on_chat_model_error":
                fields = action_fields(event)
                yield ModelFailed(
                    **common_fields(),
                    **fields,
                    model_name=event.get("name"),
                    duration_ms=duration_ms(fields["call_id"]),
                    error_message=str(data.get("error", "model call failed")),
                )
            elif event_name == "on_tool_start":
                fields = action_fields(event)
                action_started_at[fields["call_id"]] = monotonic()
                yield ToolStarted(
                    **common_fields(),
                    tool_name=event.get("name", "tool"),
                    tool_input=data.get("input"),
                    call_id=fields["call_id"],
                    node_name=fields["node_name"],
                    parent_ids=fields["parent_ids"],
                )
            elif event_name == "on_tool_end":
                fields = action_fields(event)
                output = data.get("output")
                content = getattr(output, "content", None)
                if content is not None:
                    output = content
                if not isinstance(output, str):
                    output = json.dumps(output, ensure_ascii=False, default=str)
                yield ToolFinished(
                    **common_fields(),
                    tool_name=event.get("name", "tool"),
                    tool_output=output,
                    call_id=fields["call_id"],
                    node_name=fields["node_name"],
                    parent_ids=fields["parent_ids"],
                    duration_ms=duration_ms(fields["call_id"]),
                )
            elif event_name == "on_tool_error":
                fields = action_fields(event)
                yield ToolFailed(
                    **common_fields(),
                    tool_name=event.get("name", "tool"),
                    error_message=str(data.get("error", "tool call failed")),
                    call_id=fields["call_id"],
                    node_name=fields["node_name"],
                    parent_ids=fields["parent_ids"],
                    duration_ms=duration_ms(fields["call_id"]),
                )
            elif event_name == "on_chain_end" and not event.get("parent_ids"):
                output = data.get("output")
                if isinstance(output, dict) and "messages" in output:
                    final_values = output

        # 最终状态以 aget_state 为准（on_chain_end 的 output 可能不含 parsed 等字段）
        final_state = dict((await self.graph.aget_state(config)).values)

        if final_values is None:
            final_values = final_state
        message_value = _last_message(final_values)
        if message_value is None:
            raise RuntimeError("graph finished without an assistant message")

        final_message = ChatMessage.assistant(_text_from_content(message_value.content))
        yield MessageCreated(
            run_id=run_id,
            agent_id=self.info.agent_id,
            session_id=session_id,
            **event_fields(),
            message=final_message,
        )
        parsed = final_state.get("parsed")
        schema = getattr(self.graph, "forge_output_schema", None)
        if parsed is not None and schema is not None and not isinstance(parsed, schema):
            try:
                parsed = schema.model_validate(parsed)
            except Exception:
                pass  # 还原失败保持 dict，不阻断结果
        yield RunFinished(
            run_id=run_id,
            agent_id=self.info.agent_id,
            session_id=session_id,
            **event_fields(),
            message=final_message,
            parsed=parsed,
            duration_ms=run_context.elapsed_ms if run_context is not None else None,
            model_calls=run_context.model_calls if run_context is not None else 0,
            tool_calls=run_context.tool_calls if run_context is not None else 0,
            usage=run_context.usage if run_context is not None else {},
        )
