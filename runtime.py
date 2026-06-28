import uuid
from collections.abc import AsyncIterator
from events import MessageCreated, TurnStarted, TurnFinished
from messages import Message

class AgentRuntime:
    def __init__(self):
        self.messages: list[Message] = []
        
    async def submit(self, text: str) -> AsyncIterator[object]:
        turn_id = str(uuid.uuid4())
        yield TurnStarted(turn_id=turn_id)
        
        user_message = Message(role="user", content=text)
        self.messages.append(user_message)
        yield MessageCreated(message=user_message)
        
        # 先模拟模型输出，后面替换为真实调用模型
        assistant_message = Message(role="assistant", content="收到")
        self.messages.append(assistant_message)
        yield MessageCreated(message=assistant_message)
        
        yield TurnFinished(turn_id=turn_id)