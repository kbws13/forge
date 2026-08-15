from __future__ import annotations

from uuid import uuid4

from kbws_forge_runtime.errors import SessionNotFoundError, SessionOwnerError
from kbws_forge_runtime.models import UserSession


class SessionManager:
    """
    In-memory Session
    """

    def __init__(self) -> None:
        self._sessions: dict[str, UserSession] = {}
        self._user_sessions: dict[tuple[str, str], str] = {}

    def create(self, agent_id: str, user_id: str) -> UserSession:
        key = (agent_id, user_id)
        existing_id = self._user_sessions.get(key)
        if existing_id is not None:
            return self._sessions[existing_id]

        session = UserSession(
            session_id=str(uuid4()),
            agent_id=agent_id,
            user_id=user_id,
        )
        self._sessions[session.session_id] = session
        self._user_sessions[key] = session.session_id
        return session

    def get(self, session_id: str, *, agent_id: str, user_id: str) -> UserSession:
        try:
            session = self._sessions[session_id]
        except KeyError as exc:
            raise SessionNotFoundError(f"session does not exist: {session_id}") from exc

        if session.agent_id != agent_id or session.user_id != user_id:
            raise SessionOwnerError(f"session does not belong to agent/user: {session_id}")

        return session

    def find(self, session_id: str) -> UserSession:
        try:
            return self._sessions[session_id]
        except KeyError as exc:
            raise SessionNotFoundError(f"session does not exist: {session_id}") from exc
