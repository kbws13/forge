"""LLM provider factory."""

from __future__ import annotations

from langchain_openai import ChatOpenAI

from app.core.config import Settings


def build_model(settings: Settings) -> ChatOpenAI:
    return ChatOpenAI(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        model=settings.deepseek_model,
        temperature=0,
    )
