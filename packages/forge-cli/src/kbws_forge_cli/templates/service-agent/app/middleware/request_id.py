"""Attach a request id (client-provided or generated) and expose it to logs."""

from __future__ import annotations

from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.logging import request_id_var

RESPONSE_HEADER = "X-Request-ID"


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get(RESPONSE_HEADER) or str(uuid4())
        token = request_id_var.set(request_id)
        try:
            response = await call_next(request)
            response.headers[RESPONSE_HEADER] = request_id
            return response
        finally:
            request_id_var.reset(token)
