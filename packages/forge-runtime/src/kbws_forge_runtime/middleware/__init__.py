"""Model-level middleware, aligned with the deepagents middleware model.

Middlewares intercept every model call inside ``build_chat_graph``:
- ``before_model`` can rewrite the prompt
- ``after_model`` can rewrite the response
- ``wrap_model_call`` fully wraps the call (fallback, caching, retries)
"""

from kbws_forge_runtime.middleware.base import ModelMiddleware
from kbws_forge_runtime.middleware.builtin import (
    AppendSystemContextMiddleware,
    CallCountMiddleware,
    LoggingMiddleware,
)

__all__ = [
    "ModelMiddleware",
    "AppendSystemContextMiddleware",
    "CallCountMiddleware",
    "LoggingMiddleware",
]
