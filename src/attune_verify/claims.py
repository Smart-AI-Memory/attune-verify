"""Claim observations and opt-in publication policies.

The denominator is extracted supported claims, never all factual assertions.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from attune_verify.result import Finding


class ClaimStatus(str, Enum):
    """Outcome against a declared source of truth."""

    VERIFIED = "verified"
    REFUTED = "refuted"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Claim:
    """A supported claim and the exact scope of its observation."""

    kind: str
    subject: str
    status: ClaimStatus
    evidence: str
    location: str | None = None
    detail: str = ""
    source: str | None = None

    @property
    def id(self) -> str:
        """Content/location identity within a document; changes when moved."""
        raw = "\0".join((self.kind, self.subject, self.evidence, self.location or ""))
        return hashlib.sha256(raw.encode()).hexdigest()

    def to_dict(self) -> dict:
        """Serialize a stable JSON-compatible observation."""
        return {"id": self.id, **asdict(self), "status": self.status.value}


@dataclass(frozen=True)
class VerificationPolicy:
    """Strict publication by default; legacy ok remains error-only."""

    allow_unknown: bool = False
    require_claims: bool = True
    required_kinds: tuple[str, ...] = ()


class Observations(list):
    """Internal list-compatible checker result with positive evidence."""

    def __init__(self, findings: list, claims: list[Claim]) -> None:
        super().__init__(findings)
        self.claims = claims


def record(
    claims: list[Claim] | None,
    kind: str,
    subject: str,
    evidence: str,
    location: str | None = None,
    finding: Finding | None = None,
    unknown: str | None = None,
    source: str | None = None,
) -> None:
    """Record one observed claim without changing legacy finding behavior."""
    if claims is None:
        return
    status = ClaimStatus.VERIFIED
    if finding is not None:
        status = ClaimStatus.REFUTED if finding.severity == "error" else ClaimStatus.UNKNOWN
    elif unknown:
        status = ClaimStatus.UNKNOWN
    claims.append(
        Claim(
            kind,
            subject,
            status,
            evidence,
            location,
            finding.detail if finding else (unknown or ""),
            source,
        )
    )
