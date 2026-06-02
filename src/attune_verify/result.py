"""Result types for attune-verify.

Public: FindingKind, Finding, VerifyResult, VerificationError, raise_if_failed
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List


class FindingKind(str, Enum):
    """Typed kinds matching the four verification modes."""

    UNRESOLVED_IMPORT = "unresolved_import"
    UNKNOWN_FLAG = "unknown_flag"
    DEAD_LINK = "dead_link"
    COUNT_MISMATCH = "count_mismatch"
    SEMANTIC = "semantic"


@dataclass(frozen=True)
class Finding:
    """A single verification finding."""

    kind: FindingKind
    detail: str
    evidence: str
    location: str | None = None
    severity: str = "error"  # "error" | "warning"


@dataclass
class VerifyResult:
    """The result of a verify() call."""

    findings: List[Finding] = field(default_factory=list)
    checked: List[str] = field(default_factory=list)
    semantic_ran: bool = False

    @property
    def ok(self) -> bool:
        """True when no error-severity findings exist."""
        return not any(f.severity == "error" for f in self.findings)


class VerificationError(Exception):
    """Raised by raise_if_failed() when the result is not ok."""

    def __init__(self, result: VerifyResult) -> None:
        self.result = result
        kinds = [f.kind.value for f in result.findings if f.severity == "error"]
        super().__init__(f"Verification failed: {', '.join(kinds)}")


def raise_if_failed(result: VerifyResult) -> None:
    """Opt-in hard gate — raise VerificationError if result.ok is False."""
    if not result.ok:
        raise VerificationError(result)
