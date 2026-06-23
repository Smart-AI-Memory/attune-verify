"""Count checker — verifies numeric claims match caller-supplied sources."""

from __future__ import annotations

from typing import Callable, Dict, List, Union

from attune_verify._extract import NumericClaim
from attune_verify.result import Finding, FindingKind


def check_counts(
    claims: List[NumericClaim],
    count_sources: Dict[str, Union[int, Callable[[], int]]],
) -> List[Finding]:
    """Verify numeric claims match count_sources values.

    Counts cannot be inferred — the caller must supply them. Any numeric
    claim in the content is matched against count_sources by value. Claims
    with no matching source entry are flagged as warnings (unverifiable),
    not errors.

    Args:
        claims: Numeric claims extracted from generated content.
        count_sources: Expected values keyed by label/description.
            Values may be plain ints or zero-argument callables.

    Returns:
        List of findings for mismatched or unverifiable counts.
    """
    if not count_sources:
        return []

    resolved_sources: Dict[str, int] = {}
    for label, value in count_sources.items():
        resolved_sources[label] = value() if callable(value) else value

    findings: List[Finding] = []

    for claim in claims:
        # Match each claim to the source its surrounding text names, then
        # compare against THAT source's value. Comparing against a global set
        # of all values lets a claim pass on a coincidental match with an
        # unrelated source (e.g. "12 tests" passing because some other source
        # also equals 12) — cross-contamination.
        close_label = _find_close_label(claim.context, resolved_sources)
        if close_label is not None and claim.value != resolved_sources[close_label]:
            expected = resolved_sources[close_label]
            findings.append(
                Finding(
                    kind=FindingKind.COUNT_MISMATCH,
                    detail=(
                        f"Count {claim.value} doesn't match "
                        f"'{close_label}' (expected {expected})"
                    ),
                    evidence=claim.context,
                    location=f"line {claim.line}" if claim.line else None,
                    severity="error",
                )
            )
    return findings


def _find_close_label(
    context: str,
    sources: Dict[str, int],
) -> str | None:
    """Find a source label whose keywords appear in the claim's context."""
    context_lower = context.lower()
    for label in sources:
        words = label.lower().split()
        if any(w in context_lower for w in words if len(w) > 3):
            return label
    return None
