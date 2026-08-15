from fastapi import FastAPI
from kbws_forge_runtime.api import create_agent_router

from .agent_config import build_runtime
from .settings import Settings

runtime = build_runtime(Settings())

app = FastAPI(title="Forge Runtime Java Parity Example")
app.include_router(create_agent_router(runtime))
