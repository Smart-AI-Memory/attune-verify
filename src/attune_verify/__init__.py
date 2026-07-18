"""attune-verify — generation fact-checker.

Verifies named entities in LLM-generated content actually exist:
imports import, CLI flags are real, links resolve, counts match source.

Public API::

    from attune_verify import verify, VerifyContext, VerifyResult
    from attune_verify import Finding, FindingKind
    from attune_verify import VerificationError, raise_if_failed
    from attune_verify.semantic.protocol import Judge, SemanticVerdict
"""

from __future__ import annotations

from attune_verify._verify import verify
from attune_verify.context import VerifyContext
from attune_verify.result import (
    Finding,
    FindingKind,
    VerificationError,
    VerifyResult,
    raise_if_failed,
)

__version__ = "0.2.2"
__all__ = [
    "verify",
    "VerifyContext",
    "VerifyResult",
    "Finding",
    "FindingKind",
    "VerificationError",
    "raise_if_failed",
]
