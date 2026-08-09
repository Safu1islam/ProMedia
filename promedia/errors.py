"""Error taxonomy.

Every failure path in ProMedia raises one of these. Protocol 05 forbids silent
failure: each error carries a machine-readable ``code`` so both surfaces can
report it identically, and a ``detail`` mapping so an agent can act on it
without parsing prose.
"""

from __future__ import annotations

from typing import Any


class ProMediaError(Exception):
    """Base class. Never raised directly."""

    code = "ERROR"
    exit_code = 1

    def __init__(self, message: str, **detail: Any) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail

    def to_dict(self) -> dict[str, Any]:
        return {"ok": False, "error": self.code, "message": self.message, "detail": self.detail}


class ValidationError(ProMediaError):
    """A parameter was missing, malformed, or out of range."""

    code = "VALIDATION"
    exit_code = 2


class NotFound(ProMediaError):
    code = "NOT_FOUND"


class Forbidden(ProMediaError):
    """The principal lacks authority for this operation (F-2).

    Exit code 3 is distinct so an agent can tell "I am not allowed to do this"
    apart from "this failed". The first means hand it to the operator; the
    second means retry or report.
    """

    code = "FORBIDDEN"
    exit_code = 3


class EntityLocked(ProMediaError):
    """Another agent owns this entity (C-19). Take a different ready task."""

    code = "ENTITY_LOCKED"


class CeilingExceeded(ProMediaError):
    """Admission control refused the reservation (F-7).

    Carries ``shortfall_bytes`` so the caller knows how much must be released.
    """

    code = "CEILING_EXCEEDED"


class RightsBlocked(ProMediaError):
    """The rights gate refused (F-3). Never overridable by an agent."""

    code = "RIGHTS_BLOCKED"


class ApprovalRequired(ProMediaError):
    """Operator approval is absent (F-2)."""

    code = "APPROVAL_REQUIRED"
    exit_code = 3


class IntegrityError(ProMediaError):
    """A sealed record failed verification (F-8)."""

    code = "INTEGRITY"


class LedgerDrift(ProMediaError):
    """The storage ledger and reality disagree (F-7).

    Raised rather than swallowed: the ledger is the only source of truth for
    usage, so an unnoticed mismatch means the ceiling silently stops being a
    ceiling.
    """

    code = "LEDGER_DRIFT"


class ConfigurationError(ProMediaError):
    code = "CONFIGURATION"
    exit_code = 2
