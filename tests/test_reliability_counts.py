"""Count observations must retain the assertion and its actual truth source."""

import pytest

from attune_verify import VerifyContext, verify


@pytest.mark.parametrize(
    "content",
    [
        "Tests: 12; plugins: 34.",
        "Tests: 12\nplugins: 34.",
        "| tests | 12 |\n| plugins | 34 |",
        "12 tests and 34 plugins.",
    ],
)
def test_equivalent_count_layouts_bind_to_the_same_sources(content):
    for sources in ({"tests": 12, "plugins": 34}, {"plugins": 34, "tests": 12}):
        result = verify(content, VerifyContext(count_sources=sources))
        assert result.passes(), result.to_dict()
        assert [(c.subject, c.source) for c in result.claims] == [
            ("12", "tests"),
            ("34", "plugins"),
        ]


@pytest.mark.parametrize("separator", ["; ", "\n", "\n\n"])
def test_equal_values_cannot_hide_an_incorrect_label_first_count(separator):
    result = verify(
        f"Tests: 12{separator}plugins: 12.",
        VerifyContext(count_sources={"tests": 99, "plugins": 12}),
    )
    assert not result.ok
    assert [(c.source, c.status) for c in result.claims] == [
        ("tests", "refuted"),
        ("plugins", "verified"),
    ]


@pytest.mark.parametrize(
    "text,expected", [("There are -12 widgets.", -12), ("There are +12 widgets.", 12)]
)
def test_signed_count_preserves_the_claim(text, expected):
    result = verify(text, VerifyContext(count_sources={"widgets": expected}))
    assert result.passes()
    assert result.claims[0].subject == str(expected)


def test_negative_count_never_verifies_as_positive():
    result = verify("There are -12 widgets.", VerifyContext(count_sources={"widgets": 12}))
    assert not result.ok and not result.passes()


def test_oversized_integer_retains_counts_before_and_after_it():
    result = verify(
        "There are 99 widgets.\n\n" + "1" * 5000 + " widgets.\n\nThere are 12 widgets.",
        VerifyContext(count_sources={"widgets": 12}),
    )
    assert not result.ok
    assert [c.status for c in result.claims] == ["refuted", "unknown", "verified"]


def test_unrelated_clause_cannot_donate_its_source():
    result = verify(
        "There are 12 unlabelled objects; plugins are supported.",
        VerifyContext(count_sources={"plugins": 12}),
    )
    assert result.claims[0].status == "unknown"
