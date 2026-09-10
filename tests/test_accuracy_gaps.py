"""Executable counterexamples from the critical product review."""

from attune_verify import VerifyContext, verify
from attune_verify.semantic.protocol import SemanticVerdict


def test_imported_symbol_must_exist():
    result = verify("```python\nfrom pathlib import UnicornFactory\n```", VerifyContext())
    assert not result.ok
    assert "UnicornFactory" in result.findings[0].detail


def test_explicit_invalid_python_cannot_pass():
    result = verify("```python\nimport missing_package_zz\nif:\n```", VerifyContext())
    assert not result.ok


def test_correct_multi_count_sentence_is_order_independent():
    for sources in ({"widgets": 12, "tests": 10}, {"tests": 10, "widgets": 12}):
        result = verify("There are 12 widgets and 10 tests.", VerifyContext(count_sources=sources))
        assert result.ok, result.findings


def test_negative_semantic_verdict_needs_no_explanation_to_fail():
    class Judge:
        def score(self, query, answer, passages):
            return SemanticVerdict(faithful=False)

    result = verify("a claim", VerifyContext(semantic=True, judge=Judge(), passages="source"))
    assert not result.ok


def test_positional_argument_does_not_replace_command():
    result = verify("`mytool file.txt --madeup`", VerifyContext(help_commands={"mytool": "--real"}))
    assert not result.ok
