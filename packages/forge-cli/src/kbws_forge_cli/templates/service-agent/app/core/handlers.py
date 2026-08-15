"""Global exception handlers -> unified response envelope (mirrors @RestControllerAdvice)."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.enums import ErrorCode
from app.core.exceptions import AppException
from app.core.response import error

logger = logging.getLogger("demo.handlers")


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppException)
    async def _app_exception(_request: Request, exc: AppException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content=error(exc.code, exc.info).model_dump(),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        logger.warning("invalid request path=%s errors=%s", request.url.path, exc.errors())
        return JSONResponse(
            status_code=400,
            content=error(ErrorCode.PARAMS_ERROR).model_dump(),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error path=%s", request.url.path)
        return JSONResponse(
            status_code=500,
            content=error(ErrorCode.SYSTEM_ERROR).model_dump(),
        )
