"""Composable, code-first prompts.

Prompt components are plain Python objects: compose them, partially apply
variables, and let the runtime inject session history and workflow outputs.
"""

from kbws_forge_runtime.prompts.base import Message, Prompt, compose
from kbws_forge_runtime.prompts.render import render_instruction

__all__ = ["Message", "Prompt", "compose", "render_instruction"]
