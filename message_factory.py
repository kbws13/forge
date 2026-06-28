from messages import Message

def create_user_message(text: str) -> Message:
    return Message(role="user", content=text)

def create_assistant_message(text: str) -> Message:
    return Message(role="assistant", content=text)

def create_system_message(text: str) -> Message:
    return Message(role="system", content=text)