class ForgeRuntimeError(Exception):
    code = "0001"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code
        self.message = message


class AgentNotFoundError(ForgeRuntimeError):
    code = "E0001"


class SessionNotFoundError(ForgeRuntimeError):
    code = "0002"


class SessionOwnerError(ForgeRuntimeError):
    code = "0003"


class IllegalParameterError(ForgeRuntimeError):
    code = "0004"


class RunError(ForgeRuntimeError):
    code = "0005"


class McpConfigError(ForgeRuntimeError):
    code = "0006"
