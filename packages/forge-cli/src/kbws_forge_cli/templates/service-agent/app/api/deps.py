"""Dependency injection: settings + runtime singletons (controller injection layer)."""

from __future__ import annotations

from fastapi import Request

from app.core.config import Settings


def get_settings(request: Request) -> Settings:
    """Settings 由 create_app 注入（app.state），测试可覆盖。"""
    return request.app.state.settings


def get_runtime(request: Request):
    """Runtime is built once in the app lifespan and exposed via app.state."""
    return request.app.state.runtime
