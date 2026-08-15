import pytest

from kbws_forge_runtime import AgentInfo, AgentNotFoundError, SessionOwnerError
from kbws_forge_runtime._internal.agent_handle import AgentHandle
from kbws_forge_runtime._internal.registry import AgentRegistry
from kbws_forge_runtime._internal.sessions import SessionManager


def test_registry_registers_and_lists_agents() -> None:
    registry = AgentRegistry()
    info = AgentInfo(agent_id="demo", name="Demo")
    registry.register(AgentHandle(info=info, graph=object()))
    assert registry.get("demo").info == info
    assert registry.list_agents() == [info]


def test_registry_rejects_duplicates_and_unknown_agents() -> None:
    registry = AgentRegistry()
    handle = AgentHandle(info=AgentInfo(agent_id="demo", name="Demo"), graph=object())
    registry.register(handle)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(handle)
    with pytest.raises(AgentNotFoundError):
        registry.get("missing")


def test_session_is_reused_per_agent_and_user() -> None:
    sessions = SessionManager()
    first = sessions.create("agent-a", "user-a")
    second = sessions.create("agent-a", "user-a")
    another_agent = sessions.create("agent-b", "user-a")
    assert first.session_id == second.session_id
    assert another_agent.session_id != first.session_id


def test_session_checks_agent_and_user() -> None:
    sessions = SessionManager()
    session = sessions.create("agent-a", "user-a")
    with pytest.raises(SessionOwnerError):
        sessions.get(session.session_id, agent_id="agent-a", user_id="user-b")
