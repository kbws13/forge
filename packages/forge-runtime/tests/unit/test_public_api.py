from inspect import Parameter, signature

import kbws_forge_runtime as forge
from kbws_forge_runtime.plugins import LoggingPlugin, Plugin
from kbws_forge_runtime.tools import (
    McpConfigError,
    McpToolLoader,
    SkillLoader,
    SseMcpServer,
    StdioMcpServer,
    ToolBox,
    tool,
)
from kbws_forge_runtime.workflow import (
    AgentStep,
    WorkflowState,
    build_chat_graph,
    build_loop,
    build_parallel,
    build_sequence,
)


def test_root_exports_only_runtime_contract() -> None:
    assert set(forge.__all__) == {
        "AgentInfo",
        "AgentNotFoundError",
        "AgentRuntime",
        "ChatEvent",
        "ChatMessage",
        "ChatPart",
        "ChatRequest",
        "ChatResult",
        "FilePart",
        "ForgeRuntimeError",
        "IllegalParameterError",
        "InlineDataPart",
        "MessageCreated",
        "RunError",
        "RunFailed",
        "RunFinished",
        "RunStarted",
        "SessionNotFoundError",
        "SessionOwnerError",
        "TextDelta",
        "TextPart",
        "ToolFinished",
        "ToolStarted",
        "UserSession",
    }
    for internal_name in (
        "AgentHandle",
        "AgentRegistry",
        "GraphAgent",
        "LoggingPlugin",
        "Plugin",
        "SessionManager",
        "ToolBox",
        "build_chat_graph",
        "tool",
    ):
        assert not hasattr(forge, internal_name)


def test_extension_subpackages_expose_their_own_contract() -> None:
    assert AgentStep
    assert WorkflowState
    assert build_chat_graph
    assert build_loop
    assert build_parallel
    assert build_sequence
    assert McpToolLoader
    assert McpConfigError
    assert SkillLoader
    assert SseMcpServer
    assert StdioMcpServer
    assert ToolBox
    assert tool
    assert LoggingPlugin
    assert Plugin


def test_prompts_and_agent_subpackages_expose_their_contract() -> None:
    from kbws_forge_runtime.agent import Agent, load_agents
    from kbws_forge_runtime.prompts import Message, Prompt, compose, render_instruction

    assert Agent
    assert load_agents
    assert Message
    assert Prompt
    assert compose
    assert render_instruction


def test_runtime_keeps_registry_and_sessions_private() -> None:
    runtime = forge.AgentRuntime(plugins=[])
    assert not hasattr(runtime, "registry")
    assert not hasattr(runtime, "sessions")
    parameters = signature(forge.AgentRuntime).parameters
    assert list(parameters) == ["plugins"]
    assert parameters["plugins"].kind is Parameter.KEYWORD_ONLY
