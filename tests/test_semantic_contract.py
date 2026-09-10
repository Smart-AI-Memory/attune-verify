"""Semantic receipts must carry grounding, failures and the original document."""

import pytest

from attune_verify import VerifyContext, verify
from attune_verify.semantic.protocol import SemanticVerdict


@pytest.mark.parametrize(
    "faithful,issues,status",
    [(True, [], "verified"), (False, ["unsupported API"], "refuted"), (False, [], "refuted")],
)
def test_semantic_claim_and_grounding(faithful, issues, status):
    class Judge:
        def score(self, *, query, answer, passages):
            assert query == "Verify this generated content for faithfulness"
            assert answer == "Original document"
            assert passages == ["independent evidence"]
            return SemanticVerdict(faithful, issues)

    result = verify(
        "Original document",
        VerifyContext(semantic=True, judge=Judge(), passages=["independent evidence"]),
    )
    assert result.semantic_ran
    assert result.status == status
    assert result.checked == ["imports", "flags", "links", "counts"]
    claim = result.claims[0].to_dict()
    assert claim["kind"] == "semantic"
    assert claim["subject"] == "document faithfulness"
    assert claim["evidence"] == "Original document"
    assert claim["status"] == status
    assert claim["location"] is None
    assert claim["source"] is None
    assert len(claim["id"]) == 64
    expected = issues or (
        [] if faithful else ["Semantic judge rejected the content without an explanation"]
    )
    assert [f.detail for f in result.findings] == expected
    assert all(
        f.evidence == ""
        and f.severity == "error"
        and f.kind.value == "semantic"
        and f.location is None
        for f in result.findings
    )
    assert claim["detail"] == (expected[-1] if expected else "")


@pytest.mark.parametrize(
    "judge,passages,detail",
    [
        (
            None,
            None,
            "Semantic layer requested (context.semantic=True) but no judge "
            "was provided in VerifyContext.judge",
        ),
        (
            object(),
            "source",
            "Semantic layer requested (context.semantic=True) but the "
            "provided judge (object) does not satisfy the Judge protocol "
            "(missing a compatible score())",
        ),
    ],
)
def test_unavailable_semantic_receipt(judge, passages, detail):
    result = verify(
        "Original document", VerifyContext(semantic=True, judge=judge, passages=passages)
    )
    assert not result.semantic_ran
    assert result.ok and not result.passes()
    claim = result.claims[0]
    assert (claim.kind, claim.subject, claim.status, claim.evidence, claim.detail) == (
        "semantic",
        "document faithfulness",
        "unknown",
        "Original document",
        detail,
    )
    finding = result.findings[0]
    assert (finding.kind.value, finding.evidence, finding.severity, finding.detail) == (
        "semantic",
        "",
        "warning",
        detail,
    )
