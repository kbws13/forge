"""Business exception carrying a stable error code + HTTP status."""

from __future__ import annotations

from app.core.enums import ERROR_MESSAGES, ErrorCode


class AppException(Exception):
    """Raised by services/routes; translated to the unified response by handlers."""

    def __init__(
        self,
        code: int = ErrorCode.OPERATION_ERROR,
        info: str | None = None,
        *,
        http_status: int = 400,
    ) -> None:
        super().__init__(info or ERROR_MESSAGES.get(code, "未知错误"))
        self.code = code
        self.info = info or ERROR_MESSAGES.get(code, "未知错误")
        self.http_status = http_status
