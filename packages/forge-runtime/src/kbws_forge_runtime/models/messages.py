from __future__ import annotations

import base64
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class TextPart(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["text"] = "text"
    text: str = Field(min_length=1)


class FilePart(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["file"] = "file"
    uri: str = Field(min_length=1)
    mime_type: str = Field(min_length=1)


class InlineDataPart(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["inline_data"] = "inline_data"
    data: bytes = Field(min_length=1)
    mime_type: str = Field(min_length=1)

    @field_serializer("data", when_used="json")
    def serialize_data(self, data: bytes) -> str:
        return base64.b64encode(data).decode("ascii")


ChatPart = Annotated[TextPart | FilePart | InlineDataPart, Field(discriminator="type")]


class ChatMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: Literal["user", "assistant", "system", "tool"]
    parts: tuple[ChatPart, ...] = Field(min_length=1)

    @classmethod
    def user(cls, text: str) -> ChatMessage:
        return cls(role="user", parts=(TextPart(text=text),))

    @classmethod
    def assistant(cls, text: str) -> ChatMessage:
        return cls(role="assistant", parts=(TextPart(text=text),))

    @property
    def text(self) -> str:
        return "".join(part.text for part in self.parts if isinstance(part, TextPart))
