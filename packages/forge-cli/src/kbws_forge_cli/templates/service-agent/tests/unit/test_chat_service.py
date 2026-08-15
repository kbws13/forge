from app.core.enums import ErrorCode
from app.core.exceptions import AppException
from app.core.utils import sse_frame
from app.services.chat_service import _map_code


def test_sdk_error_code_mapping() -> None:
    from kbws_forge_runtime.errors import (
        AgentNotFoundError,
        IllegalParameterError,
        SessionNotFoundError,
        SessionOwnerError,
    )

    assert _map_code(AgentNotFoundError("x")) == ErrorCode.NOT_FOUND
    assert _map_code(SessionNotFoundError("x")) == ErrorCode.NOT_FOUND
    assert _map_code(SessionOwnerError("x")) == ErrorCode.FORBIDDEN
    assert _map_code(IllegalParameterError("x")) == ErrorCode.PARAMS_ERROR


def test_unknown_code_falls_back_to_operation_error() -> None:
    from kbws_forge_runtime.errors import ForgeRuntimeError

    assert _map_code(ForgeRuntimeError("x", code="9999")) == ErrorCode.OPERATION_ERROR


def test_app_exception_defaults() -> None:
    exc = AppException(ErrorCode.NOT_FOUND)
    assert exc.code == 40400
    assert exc.http_status == 400
    assert exc.info == "请求数据不存在"


def test_sse_frame_serializes_pydantic() -> None:
    from app.core.response import ok

    frame = sse_frame("data", ok({"x": 1}))
    assert frame.startswith("event: data\n")
    assert '"code":0' in frame
    assert frame.endswith("\n\n")
