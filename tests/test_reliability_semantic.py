"""Semantic evidence cannot create substantive claims from empty input."""

import pytest

from attune_verify import VerifyContext, verify
from attune_verify.semantic.protocol import SemanticVerdict


class ForbiddenJudge:
    called = False

    def score(self, *args, **kwargs):
        self.called = True
        raise AssertionError("An empty document or empty grounding must not invoke a judge")


@pytest.mark.parametrize("content", ["", " \n\t"])
def test_empty_content_remains_unknown_without_running_judge(content):
    judge = ForbiddenJudge()
    result = verify(content, VerifyContext(semantic=True, judge=judge, passages="source"))
    assert not judge.called
    assert result.ok and not result.passes()
    assert not result.semantic_ran
    assert "empty" in result.claims[0].detail.lower()


@pytest.mark.parametrize("passages", ["  ", [""], ["", " \t"]])
def test_blank_grounding_is_unknown_before_judge_invocation(passages):
    judge = ForbiddenJudge()
    result = verify(
        "A substantive claim", VerifyContext(semantic=True, judge=judge, passages=passages)
    )
    assert not judge.called
    assert result.ok and not result.passes()
    assert "passages" in result.claims[0].detail.lower()
    assert "judge failed" not in result.claims[0].detail.lower()


def test_nonempty_grounding_is_normalized():
    class Judge:
        def score(self, *, query, answer, passages):
            assert passages == ["independent evidence"]
            return SemanticVerdict(True)

    result = verify(
        "A substantive claim",
        VerifyContext(semantic=True, judge=Judge(), passages=["", " independent evidence ", " "]),
    )
    assert result.passes()
