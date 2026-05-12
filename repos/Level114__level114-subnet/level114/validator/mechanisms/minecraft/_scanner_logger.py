"""Logging adapter that proxies scanner messages to bittensor."""

from __future__ import annotations

from typing import Any

import bittensor as bt


class _BTScannerLogger:
    """Adapter that forwards standard logging calls to bittensor's logger."""

    prefix = "[Scanner]"

    @staticmethod
    def _format(message: str, *args: Any) -> str:
        if not args:
            return message
        try:
            return message % args
        except Exception:  # noqa: BLE001
            try:
                return message.format(*args)
            except Exception:  # noqa: BLE001
                joined = " ".join(str(arg) for arg in args)
                return f"{message} {joined}"

    def info(self, message: str, *args: Any, **kwargs: Any) -> None:  # noqa: D401
        bt.logging.info(f"{self.prefix} {self._format(message, *args)}")

    def warning(self, message: str, *args: Any, **kwargs: Any) -> None:
        bt.logging.warning(f"{self.prefix} {self._format(message, *args)}")

    def error(self, message: str, *args: Any, **kwargs: Any) -> None:
        bt.logging.error(f"{self.prefix} {self._format(message, *args)}")

    def debug(self, message: str, *args: Any, **kwargs: Any) -> None:
        bt.logging.debug(f"{self.prefix} {self._format(message, *args)}")
