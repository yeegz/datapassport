"""Exceptions raised by DataPassport.

Every error DataPassport raises on purpose derives from :class:`DataPassportError`
and carries a short ``hint`` saying what to try next.
"""

from __future__ import annotations


class DataPassportError(Exception):
    """Base class for all DataPassport errors."""

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint

    def __str__(self) -> str:
        if self.hint:
            return f"{self.message}\n  hint: {self.hint}"
        return self.message


class SourceError(DataPassportError):
    """A dataset could not be found, opened or parsed."""


class ContractError(DataPassportError):
    """A contract file is missing, malformed or refers to unknown rules."""


class IncompatibleError(DataPassportError):
    """Two passports cannot be compared (different fingerprint spec or options)."""


class PluginError(DataPassportError):
    """A plugin, custom rule, metric or source adapter failed."""


class CheckFailed(DataPassportError):
    """Raised by :meth:`CheckReport.raise_for_status` when a check fails."""
