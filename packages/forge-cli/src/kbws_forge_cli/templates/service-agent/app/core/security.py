"""API key authentication (AOP-style, mirrors AuthCheck annotation + interceptor)."""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, Request

from app.api.deps import get_settings
from app.core.config import Settings
from app.core.enums import ErrorCode
from app.core.exceptions import AppException


def require_api_key(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    """FastAPI dependency: reject requests without a valid API key.

    Accepts ``X-API-Key: <key>`` or ``Authorization: Bearer <key>``.
    Attach to a route via ``Depends(require_api_key)``.
    """
    if not settings.api_key:
        return  # 未配置 key：仅限本地调试

    header = request.headers.get("X-API-Key")
    auth = request.headers.get("Authorization", "")
    if header:
        provided = header
    elif auth.startswith("Bearer "):
        provided = auth[len("Bearer "):]
    else:
        raise AppException(ErrorCode.NOT_LOGIN, http_status=401)

    if not hmac.compare_digest(provided, settings.api_key):
        raise AppException(ErrorCode.NO_AUTH, http_status=403)
