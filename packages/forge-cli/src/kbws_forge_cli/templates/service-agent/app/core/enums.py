"""Business error codes, mirroring the reference backend's ErrorCode."""

from __future__ import annotations


class ErrorCode:
    SUCCESS = 0
    PARAMS_ERROR = 40000
    NOT_LOGIN = 40100
    NO_AUTH = 40101
    FORBIDDEN = 40300
    NOT_FOUND = 40400
    OPERATION_ERROR = 50001
    SYSTEM_ERROR = 50000


ERROR_MESSAGES: dict[int, str] = {
    ErrorCode.SUCCESS: "ok",
    ErrorCode.PARAMS_ERROR: "请求参数错误",
    ErrorCode.NOT_LOGIN: "未登录",
    ErrorCode.NO_AUTH: "无权限",
    ErrorCode.FORBIDDEN: "禁止访问",
    ErrorCode.NOT_FOUND: "请求数据不存在",
    ErrorCode.OPERATION_ERROR: "操作失败",
    ErrorCode.SYSTEM_ERROR: "系统内部异常",
}
