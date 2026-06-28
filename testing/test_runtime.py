import unittest
import uuid

from events import MessageCreated, TurnFinished, TurnStarted
from runtime import AgentRuntime


async def collect(async_iterable):
    items = []
    async for item in async_iterable:
        items.append(item)
    return items


class AgentRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_submit_emits_expected_events_in_order(self):
        runtime = AgentRuntime()

        events = await collect(runtime.submit("你好"))

        self.assertEqual(4, len(events))
        self.assertIsInstance(events[0], TurnStarted)
        self.assertIsInstance(events[1], MessageCreated)
        self.assertIsInstance(events[2], MessageCreated)
        self.assertIsInstance(events[3], TurnFinished)
        self.assertEqual(events[0].turn_id, events[3].turn_id)
        self.assertEqual(4, uuid.UUID(events[0].turn_id).version)

    async def test_submit_records_user_and_assistant_messages(self):
        runtime = AgentRuntime()

        events = await collect(runtime.submit("测试消息"))

        user_message = events[1].message
        assistant_message = events[2].message

        self.assertEqual("user", user_message.role)
        self.assertEqual("测试消息", user_message.content)
        self.assertEqual("assistant", assistant_message.role)
        self.assertEqual("收到", assistant_message.content)
        self.assertEqual([user_message, assistant_message], runtime.messages)

    async def test_submit_accumulates_messages_across_turns(self):
        runtime = AgentRuntime()

        await collect(runtime.submit("第一轮"))
        await collect(runtime.submit("第二轮"))

        self.assertEqual(
            [
                ("user", "第一轮"),
                ("assistant", "收到"),
                ("user", "第二轮"),
                ("assistant", "收到"),
            ],
            [(message.role, message.content) for message in runtime.messages],
        )


if __name__ == "__main__":
    unittest.main()
