"""Extractor agent: structured output example (output_schema usage).

外部传入任意 pydantic schema 即可；这里示范一个嵌套结构。
"""

from kbws_forge_runtime.agent import Agent
from pydantic import BaseModel, Field

from .prompts import extract_prompt


class ExtractedInfo(BaseModel):
    """演示用的输出结构：可换成任意业务 schema。"""

    name: str = Field(description="提取出的主体名称")
    key_points: list[str] = Field(description="关键要点列表，至少 2 条")


agent = Agent(
    agent_id="extract",
    name="Extractor",
    description="将文本提取为结构化信息（output_schema 示例）。",
    prompt=extract_prompt,
    output_schema=ExtractedInfo,
)
