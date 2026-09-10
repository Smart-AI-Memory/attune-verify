"""Tests for the semantic layer (T4)."""

from attune_verify import VerifyContext, verify
from attune_verify.result import FindingKind
from attune_verify.semantic.protocol import Judge, SemanticVerdict


class FakeJudge:
    def __init__(self, faithful: bool, issues: list = None) -> None:
        self._faithful = faithful
        self._issues = issues or []

    def score(self, query: str, answer: str, passages) -> SemanticVerdict:
        return SemanticVerdict(faithful=self._faithful, issues=self._issues)


def test_fake_judge_satisfies_protocol():
    assert isinstance(FakeJudge(True), Judge)


def test_semantic_finding_when_not_faithful():
    ctx = VerifyContext(
        semantic=True,
        judge=FakeJudge(faithful=False, issues=["insecure example: host=0.0.0.0"]),
        passages="Bind the server to a loopback address in examples.",
    )
    result = verify("Some content with host=0.0.0.0", ctx)
    semantic = [f for f in result.findings if f.kind == FindingKind.SEMANTIC]
    assert len(semantic) == 1
    assert "insecure" in semantic[0].detail
    assert result.semantic_ran is True


def test_degrade_when_no_judge():
    ctx = VerifyContext(semantic=True, judge=None)
    result = verify("Some content.", ctx)
    semantic = [f for f in result.findings if f.kind == FindingKind.SEMANTIC]
    assert len(semantic) == 1
    assert semantic[0].severity == "warning"
    assert result.semantic_ran is False


def test_semantic_disabled_by_default():
    ctx = VerifyContext()
    result = verify("Some content.", ctx)
    assert result.semantic_ran is False
    assert not any(f.kind == FindingKind.SEMANTIC for f in result.findings)


class _StubFaithfulnessResult:
    """Shape of attune-rag's FaithfulnessResult: score-based, no boolean."""

    def __init__(self, unsupported: list) -> None:
        self.unsupported_claims = unsupported
        self.score = 1.0 if not unsupported else 0.5


def test_rag_verdict_faithful_when_no_unsupported_claims():
    from attune_verify.semantic.rag_adapter import _to_verdict

    verdict = _to_verdict(_StubFaithfulnessResult([]))
    assert verdict.faithful is True
    assert verdict.issues == []


def test_rag_verdict_unfaithful_carries_unsupported_claims():
    from attune_verify.semantic.rag_adapter import _to_verdict

    result = _StubFaithfulnessResult(["the /run route does not exist"])
    verdict = _to_verdict(result)
    assert verdict.faithful is False
    assert verdict.issues == ["the /run route does not exist"]
    assert verdict.raw is result


def test_malformed_semantic_verdicts_never_verify():
    for verdict in (
        SemanticVerdict(True, ["contradiction"]),
        SemanticVerdict("yes", []),
        SemanticVerdict(True, [42]),
    ):

        class MalformedJudge:
            def score(self, *args, chosen=verdict, **kwargs):
                return chosen

        result = verify(
            "plain prose", VerifyContext(semantic=True, judge=MalformedJudge(), passages="source")
        )
        assert result.status == "unknown"
        assert not result.passes()


def test_rag_adapter_rejects_malformed_result():
    import pytest

    from attune_verify.semantic.rag_adapter import _to_verdict

    with pytest.raises(ValueError):
        _to_verdict(object())
