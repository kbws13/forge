from inspect import Parameter, signature

import kbws_forge_runtime as forge
from kbws_forge_runtime.plugins import LoggingPlugin, Plugin
from kbws_forge_runtime.sinks import TraceStore
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
        "EventSink",
        "FilePart",
        "ForgeRuntimeError",
        "IllegalParameterError",
        "InMemoryEventSink",
        "InlineDataPart",
        "MessageCreated",
        "ModelExecutor",
        "ModelFailed",
        "ModelFinished",
        "ModelStarted",
        "ModelUsage",
        "RunBudgetExceededError",
        "RunCancelled",
        "RunCancelledError",
        "RunContext",
        "RunError",
        "RunFailed",
        "RunFinished",
        "RunPolicy",
        "RunStarted",
        "RunTimeoutError",
        "RunUsageUnavailableError",
        "SessionNotFoundError",
        "SessionOwnerError",
        "TextDelta",
        "TextPart",
        "ToolApprovalHandler",
        "ToolApprovalRequest",
        "ToolApprovalRequiredError",
        "ToolExecutor",
        "ToolFailed",
        "ToolFinished",
        "ToolNotAllowedError",
        "ToolPolicy",
        "ToolStarted",
        "UsageResolver",
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
    # trace_store 是公开的 trace 记录器（服务端 trace API / UI 的数据源）
    assert isinstance(runtime.trace_store, TraceStore)
    parameters = signature(forge.AgentRuntime).parameters
    assert list(parameters) == [
        "plugins",
        "default_policy",
        "event_sinks",
        "tool_approval_handler",
        "usage_resolver",
        "trace_store",
    ]
    assert parameters["plugins"].kind is Parameter.KEYWORD_ONLY
