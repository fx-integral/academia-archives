from typing import Any


class SignatureVerificationError(Exception):
    """Raised when signature verification fails.

    Optionally carries debugging context for test environments.
    """

    def __init__(self, message: str = "Invalid signature", context: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.context = context or {}


