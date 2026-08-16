from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages


def merge_outputs(left: dict[str, str] | None, right: dict[str, str] | None) -> dict[str, str]:
    return {**(left or {}), **(right or {})}


def merge_stop(left: bool | None, right: bool | None) -> bool:
    return bool(left or right)


class WorkflowState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    outputs: Annotated[dict[str, str], merge_outputs]
    round: int
    stop: Annotated[bool, merge_stop]
    # 结构化输出：由 finalize 节点写入，模型按 output_schema 返回的结果
    parsed: Any
