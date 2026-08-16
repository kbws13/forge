"""Extractor agent: demonstrates structured output (output_schema).

外部传入任意 pydantic schema，模型通过结构化输出工具返回，结果在
``ChatResult.parsed`` / 流式 ``RunFinished.parsed`` 中。
"""

from kbws_forge_runtime.prompts import Message, Prompt

extract_prompt = Prompt(
    name="extract",
    messages=[
        Message.system(
            "你是一个信息提取器。根据用户输入提取结构化信息，"
            "必须通过结构化输出工具返回，不要输出其他文本。"
        ),
    ],
)
