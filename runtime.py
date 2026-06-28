import uuid
from collections.abc import AsyncIterator
from events import MessageCreated, TurnStarted, TurnFinished, TurnCancelled, AssistantDelta
from message_factory import create_user_message, create_assistant_message
from messages import Message
import asyncio


class AgentRuntime:
    def __init__(self):
        self.messages: list[Message] = []
        self._cancel_event = asyncio.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    async def submit(self, text: str) -> AsyncIterator[object]:
        turn_id = str(uuid.uuid4())
        yield TurnStarted(turn_id=turn_id)

        if self._cancel_event.is_set():
            yield TurnCancelled(turn_id=turn_id, reason="cancelled before turn started")
            return

        user_message = create_user_message(text)
        self.messages.append(user_message)
        yield MessageCreated(message=user_message)

        # 先模拟模型输出，后面替换为真实调用模型
        assistant_text = "收到"
        yield AssistantDelta(text=assistant_text)
        assistant_message = create_assistant_message(assistant_text)
        self.messages.append(assistant_message)
        yield MessageCreated(message=assistant_message)

        yield TurnFinished(turn_id=turn_id)
