from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage

from kbws_forge_runtime.models import (
    AgentInfo,
    ChatMessage,
    FilePart,
    InlineDataPart,
    MessageCreated,
    TextDelta,
    ToolFinished,
    ToolStarted,
)


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
        content: str | list[dict[str, Any]] = message.text
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
    graph: Any

    async def stream(
        self, message: ChatMessage, *, run_id: str, session_id: str
    ) -> AsyncIterator[TextDelta | ToolStarted | ToolFinished | MessageCreated]:
        config = {
            "configurable": {"thread_id": session_id},
            "metadata": {
                "run_id": run_id,
                "agent_id": self.info.agent_id,
                "session_id": session_id,
            },
        }
        final_values: dict[str, Any] | None = None
        input_state = {"messages": [to_langchain_message(message)]}

        async for event in self.graph.astream_events(input_state, config=config, version="v2"):
            event_name = event.get("event")
            data = event.get("data", {})
            if event_name == "on_chat_model_stream":
                text = _text_from_content(getattr(data.get("chunk"), "content", ""))
                if text:
                    yield TextDelta(
                        run_id=run_id,
                        agent_id=self.info.agent_id,
                        session_id=session_id,
                        text=text,
                        node_name=event.get("metadata", {}).get("langgraph_node"),
                    )

            elif event_name == "on_tool_start":
                yield ToolStarted(
                    run_id=run_id,
                    agent_id=self.info.agent_id,
                    session_id=session_id,
                    tool_name=event.get("name", "tool"),
                    tool_input=data.get("input"),
                )
            elif event_name == "on_tool_end":
                output = data.get("output")
                if not isinstance(output, str):
                    output = json.dumps(output, ensure_ascii=False, default=str)
                yield ToolFinished(
                    run_id=run_id,
                    agent_id=self.info.agent_id,
                    session_id=session_id,
                    tool_name=event.get("name", "tool"),
                    tool_output=output,
                )
            elif event_name == "on_chain_end" and not event.get("parent_ids"):
                output = data.get("output")
                if isinstance(output, dict) and "messages" in output:
                    final_values = output
        if final_values is None:
            state = await self.graph.aget_state(config)
            final_values = dict(state.values)
        message_value = _last_message(final_values)
        if message_value is None:
            raise RuntimeError("graph finished without an assistant message")

        yield MessageCreated(
            run_id=run_id,
            agent_id=self.info.agent_id,
            session_id=session_id,
            message=ChatMessage.assistant(_text_from_content(message_value.content)),
        )
