import asyncio
from collections.abc import Callable

from events import TurnStarted, AssistantDelta, MessageCreated, TurnFailed, TurnFinished
from runtime import AgentRuntime


def render_tui_event(event: object) -> str:
    if isinstance(event, TurnStarted):
        return f"\n[turn {event.turn_id}]"
    if isinstance(event, AssistantDelta):
        return event.text
    if isinstance(event, MessageCreated) and event.message.role == "user":
        return f"> {event.message.content}"
    if isinstance(event, MessageCreated) and event.message.role == "assistant":
        return ""
    if isinstance(event, TurnFailed):
        return f"\nERROR: {event.error}"
    if isinstance(event, TurnFinished):
        return "\n"
    return ""


async def run_tui(
        runtime: AgentRuntime | None = None,
        input_fn: Callable[[str], str] = input,
        output_fn: Callable[[str], None] = print,
) -> None:
    runtime = runtime or AgentRuntime()
    output_fn("Agent Runtime TUI. 输入 :q 退出。")

    while True:
        prompt = input_fn("you> ")
        if prompt.strip() in {":q", ":quit", "exit"}:
            output_fn("bye")
            return

        async for event in runtime.submit(prompt):
            text = render_tui_event(event)
            if text:
                output_fn(text)


def main() -> None:
    asyncio.run(run_tui())


if __name__ == "__main__":
    main()
