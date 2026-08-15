"""Assistant agent: composable prompt blocks.

组件化示例：persona 块带 ``{tone}`` 变量（partial 提供默认值，调用方可覆盖），
历史通过 placeholder 由 SDK 自动注入。
"""

from kbws_forge_runtime.prompts import Message, Prompt, compose

persona = Prompt(
    name="persona",
    messages=[
        Message.system(
            "You are a helpful assistant. Use the provided tools when the user "
            "asks for the current time or arithmetic.\n"
            "回复风格：{tone}",
            # 默认值；调用方可通过 variables={"tone": ...} 覆盖
            tone="专业简洁，直接给结论",
        ),
    ],
)

assistant_prompt = compose(
    persona,
    name="assistant",
    extra_messages=[Message.history()],
)
