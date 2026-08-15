"""Unified response envelope: ``{code, info, data}`` (mirrors BaseResponse)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.core.enums import ERROR_MESSAGES, ErrorCode


class ApiResponse[T](BaseModel):
    code: int
    info: str
    data: T | None = None


def ok(data: Any = None, info: str | None = None) -> ApiResponse[Any]:
    return ApiResponse(
        code=ErrorCode.SUCCESS,
        info=info or ERROR_MESSAGES[ErrorCode.SUCCESS],
        data=data,
    )


def error(code: int, info: str | None = None) -> ApiResponse[Any]:
    return ApiResponse(code=code, info=info or ERROR_MESSAGES.get(code, "未知错误"), data=None)
