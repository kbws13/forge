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


def test_execution_error_codes_map_to_operation_error() -> None:
    from kbws_forge_runtime.errors import (
        RunBudgetExceededError,
        RunCancelledError,
        RunTimeoutError,
        RunUsageUnavailableError,
        ToolApprovalRequiredError,
        ToolNotAllowedError,
    )

    errors = (
        RunCancelledError("x"),
        RunTimeoutError("x"),
        RunBudgetExceededError("x"),
        ToolNotAllowedError("x"),
        ToolApprovalRequiredError("x"),
        RunUsageUnavailableError("x"),
    )
    assert all(_map_code(error) == ErrorCode.OPERATION_ERROR for error in errors)


def test_settings_builds_runtime_policy() -> None:
    from app.core.config import Settings

    settings = Settings(
        _env_file=None,
        deepseek_api_key="test-key",
        run_timeout_seconds=30,
        run_max_model_calls=4,
        run_max_total_tokens=2_000,
        run_model_retries=1,
        run_tool_retries=2,
        run_retryable_tools={"search"},
    )

    policy = settings.build_run_policy()
    assert policy.timeout_seconds == 30
    assert policy.max_model_calls == 4
    assert policy.max_total_tokens == 2_000
    assert policy.model_retries == 1
    assert policy.tool_retries == 2
    assert policy.tool_policy.retryable_tools == {"search"}


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
