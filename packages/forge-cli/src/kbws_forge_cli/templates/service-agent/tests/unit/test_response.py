from app.core.enums import ErrorCode
from app.core.response import ApiResponse, error, ok


def test_ok_envelope() -> None:
    payload = ok({"a": 1})
    assert isinstance(payload, ApiResponse)
    assert payload.code == ErrorCode.SUCCESS
    assert payload.info == "ok"
    assert payload.data == {"a": 1}


def test_error_envelope_uses_registry_message() -> None:
    payload = error(ErrorCode.NOT_FOUND)
    assert payload.code == 40400
    assert payload.info == "请求数据不存在"
    assert payload.data is None


def test_error_envelope_custom_info() -> None:
    payload = error(ErrorCode.PARAMS_ERROR, "agent_id 不能为空")
    assert payload.info == "agent_id 不能为空"


def test_serialization_shape() -> None:
    assert ok([1, 2]).model_dump() == {"code": 0, "info": "ok", "data": [1, 2]}
