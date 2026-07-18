"""Count checker — verifies numeric claims match caller-supplied sources."""

from __future__ import annotations

import re
from typing import Callable, Dict, List, Union

from attune_verify._extract import NumericClaim
from attune_verify.result import Finding, FindingKind

# Values in this range near a source keyword are far more likely to be years
# than counts ("Released 2026 versions of the widgets" is not a widget count).
_YEAR_MIN, _YEAR_MAX = 1900, 2099


def check_counts(
    claims: List[NumericClaim],
    count_sources: Dict[str, Union[int, Callable[[], int]]],
) -> List[Finding]:
    """Verify numeric claims match count_sources values.

    Counts cannot be inferred — the caller must supply them. Each numeric
    claim is matched to the source its surrounding text names and compared
    against that source's value. Claims whose context names no source are
    silently skipped (unverifiable without a source, and flagging every
    stray number would be noise). Year-like values (1900–2099) are compared
    only when the source keyword directly follows the number ("2026 widgets"),
    so dates near a keyword don't false-positive.

    Args:
        claims: Numeric claims extracted from generated content.
        count_sources: Expected values keyed by label/description.
            Values may be plain ints or zero-argument callables.

    Returns:
        List of findings for mismatched counts.
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
        if close_label is None:
            continue
        if _year_like(claim.value) and not _label_follows_number(claim, close_label):
            continue
        if claim.value != resolved_sources[close_label]:
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
    """Find a source label whose keywords appear in the claim's context.

    Keywords match on a leading word boundary — "test" matches "tests" but
    not "latest" — a bare substring test false-matched inside longer words.
    """
    context_lower = context.lower()
    for label in sources:
        words = label.lower().split()
        if any(re.search(rf"\b{re.escape(w)}", context_lower) for w in words if len(w) > 3):
            return label
    return None


def _year_like(value: int) -> bool:
    return _YEAR_MIN <= value <= _YEAR_MAX


def _label_follows_number(claim: NumericClaim, label: str) -> bool:
    """True when a label keyword is one of the two tokens after the number.

    "2026 widgets" reads as a widget count; "2026 versions of the widgets"
    reads as a year that merely has the keyword nearby.
    """
    match = re.search(rf"\b{claim.value}\b((?:\s+\S+){{1,2}})", claim.context.lower())
    if match is None:
        return False
    following = match.group(1)
    return any(
        re.search(rf"\b{re.escape(w)}", following) for w in label.lower().split() if len(w) > 3
    )
