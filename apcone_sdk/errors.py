from __future__ import annotations

from typing import Any


class ApconeError(Exception):
    """Base exception for Apcone SDK failures."""


class ApconeAPIError(ApconeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        detail: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


class ApconeMCPError(ApconeError):
    def __init__(self, message: str, *, tool_name: str | None = None) -> None:
        super().__init__(message)
        self.tool_name = tool_name
