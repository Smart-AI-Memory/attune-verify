"""Result types for attune-verify.

Public: FindingKind, Finding, VerifyResult, VerificationError, raise_if_failed
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List

from attune_verify.claims import Claim, ClaimStatus, VerificationPolicy


class FindingKind(str, Enum):
    """Typed kinds: the four verification modes, the semantic layer, and
    CHECKER_ERROR for infrastructure failures inside a checker itself."""

    UNRESOLVED_IMPORT = "unresolved_import"
    UNKNOWN_FLAG = "unknown_flag"
    DEAD_LINK = "dead_link"
    COUNT_MISMATCH = "count_mismatch"
    SEMANTIC = "semantic"
    CHECKER_ERROR = "checker_error"
    INVALID_CODE = "invalid_code"


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
    claims: List[Claim] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when no error-severity findings exist."""
        return not any(f.severity == "error" for f in self.findings)

    @property
    def coverage(self) -> dict[str, int]:
        """Counts of extracted supported claims, not arbitrary prose."""
        return {
            "total": len(self.claims),
            **{state.value: sum(c.status == state for c in self.claims) for state in ClaimStatus},
        }

    @property
    def status(self) -> ClaimStatus:
        """Refuted takes precedence; empty or incomplete checks are unknown."""
        if not self.ok or any(c.status == ClaimStatus.REFUTED for c in self.claims):
            return ClaimStatus.REFUTED
        if not self.claims or any(c.status == ClaimStatus.UNKNOWN for c in self.claims):
            return ClaimStatus.UNKNOWN
        if any(f.severity == "warning" for f in self.findings):
            return ClaimStatus.UNKNOWN
        return ClaimStatus.VERIFIED

    def passes(self, policy: VerificationPolicy | None = None) -> bool:
        """Apply an explicit publication policy, strict when omitted."""
        policy = policy or VerificationPolicy()
        if self.status == ClaimStatus.REFUTED or (policy.require_claims and not self.claims):
            return False
        if not set(policy.required_kinds) <= {c.kind for c in self.claims}:
            return False
        return policy.allow_unknown or self.status == ClaimStatus.VERIFIED

    def to_dict(self) -> dict:
        """Versioned report suitable for CI and CLI consumers."""
        from dataclasses import asdict

        return {
            "schema_version": 1,
            "ok": self.ok,
            "status": self.status.value,
            "checked": self.checked,
            "semantic_ran": self.semantic_ran,
            "coverage": self.coverage,
            "findings": [{**asdict(f), "kind": f.kind.value} for f in self.findings],
            "claims": [c.to_dict() for c in self.claims],
        }


class VerificationError(Exception):
    """Raised by raise_if_failed() when the result is not ok."""

    def __init__(self, result: VerifyResult) -> None:
        self.result = result
        kinds = [f.kind.value for f in result.findings if f.severity == "error"]
        super().__init__(f"Verification failed: {', '.join(kinds) or 'incomplete verification'}")


def raise_if_failed(result: VerifyResult, policy: VerificationPolicy | None = None) -> None:
    """Opt-in hard gate — raise VerificationError if result.ok is False."""
    if not (result.ok if policy is None else result.passes(policy)):
        raise VerificationError(result)
