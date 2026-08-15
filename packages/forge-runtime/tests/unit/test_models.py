import base64

import pytest

from kbws_forge_runtime import (
    ChatMessage,
    ChatRequest,
    FilePart,
    InlineDataPart,
    TextPart,
)
from kbws_forge_runtime._internal.graph_agent import to_langchain_message


def test_text_message_is_easy_to_create() -> None:
    message = ChatMessage.user("hello")
    assert message.role == "user"
    assert message.text == "hello"


def test_multimodal_message_maps_to_langchain_content_blocks() -> None:
    message = ChatMessage(
        role="user",
        parts=(
            TextPart(text="look"),
            FilePart(uri="https://example.com/cat.png", mime_type="image/png"),
            InlineDataPart(data=b"pdf", mime_type="application/pdf"),
        ),
    )
    converted = to_langchain_message(message)
    assert isinstance(converted.content, list)
    assert converted.content[0] == {"type": "text", "text": "look"}
    assert converted.content[1]["source_type"] == "url"
    assert converted.content[2]["data"] == base64.b64encode(b"pdf").decode("ascii")


def test_chat_request_only_accepts_user_messages() -> None:
    with pytest.raises(ValueError, match="role must be 'user'"):
        ChatRequest(
            agent_id="agent",
            user_id="user",
            message=ChatMessage.assistant("not user input"),
        )
