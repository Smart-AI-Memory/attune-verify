"""Regression receipts for Markdown extraction and local URL verification."""

import os

import pytest

from attune_verify import ClaimStatus, VerifyContext, verify
from attune_verify._extract import (
    extract_code_fences,
    extract_links,
    extract_numeric_claims,
)
from attune_verify.checkers.links import check_links


@pytest.mark.parametrize("marker", ["```", "~~~"])
def test_eof_fence_retains_code_and_original_line(marker):
    fences = extract_code_fences(f"Intro\n{marker}python\nimport absent_reliability_package\n")
    assert len(fences) == 1
    assert fences[0].language == "python"
    assert fences[0].line == 2
    assert fences[0].content == "import absent_reliability_package\n"


def test_truncating_rejected_python_does_not_promote_to_strict_success(tmp_path):
    (tmp_path / "real.md").touch()
    body = "[good](real.md)\n```python\nimport absent_reliability_package\n"
    for content in (body + "```\n", body):
        result = verify(content, VerifyContext(project_root=tmp_path))
        assert not result.passes()
        assert any(c.kind == "imports" and c.status == ClaimStatus.REFUTED for c in result.claims)


@pytest.mark.parametrize(
    "link,target",
    [
        ("[bad](a(b(c)).md)", "a(b(c)).md"),
        ("[bad [nested]](missing.md)", "missing.md"),
        ("[bad [a [b]]](missing.md)", "missing.md"),
        (r"[escaped](a\(b\).md)", "a(b).md"),
        ('[title](<a b.md> "Read me")', "a b.md"),
        ("[ref [nested]][target]\n\n[target]: missing.md", "missing.md"),
    ],
)
def test_nested_links_remain_in_denominator(tmp_path, link, target):
    (tmp_path / "real.md").touch()
    content = "[good](real.md)\n" + link
    result = verify(content, VerifyContext(project_root=tmp_path))
    assert not result.passes()
    assert any(c.subject == target and c.status == ClaimStatus.REFUTED for c in result.claims)
    assert next(c for c in result.claims if c.subject == target).location == "line 2"
    (tmp_path / target).touch()
    assert verify(content, VerifyContext(project_root=tmp_path)).passes()


@pytest.mark.parametrize("ticks", ["`", "``", "```", "````", "`" * 20])
def test_code_span_width_does_not_change_claim_set(ticks):
    content = f"Example {ticks}[shown](missing.md) and 99 widgets{ticks}.\n[real](real.md)"
    assert [(link.target, link.line) for link in extract_links(content)] == [("real.md", 2)]
    assert extract_numeric_claims(content) == []


@pytest.mark.parametrize(
    "example",
    [
        r"Write \[shown](missing.md).",
        "<!-- [shown](missing.md) and 99 widgets -->",
        "Write `[shown](missing.md)\nand 99 widgets`.",
        "<!-- comment ` -->\n[shown](missing.md) `",
    ],
)
def test_non_link_syntax_is_masked_without_losing_following_lines(example):
    content = example + "\n[real](real.md)"
    expected = [("real.md", example.count("\n") + 2)]
    if example.startswith("<!-- comment"):
        expected.insert(0, ("missing.md", 2))
    assert [(link.target, link.line) for link in extract_links(content)] == expected


def test_unmatched_code_span_cannot_hide_links_in_later_paragraphs():
    content = "An unmatched ` code delimiter.\n\n[real](real.md)\n\nAnother `."
    assert [(link.target, link.line) for link in extract_links(content)] == [("real.md", 3)]


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
@pytest.mark.parametrize("blank", ["", " \t "], ids=["empty", "space-tab"])
def test_blank_paragraph_boundaries_preserve_claims_across_line_endings(tmp_path, newline, blank):
    (tmp_path / "real.md").touch()
    content = newline.join(
        [
            "`unmatched",
            blank,
            "[bad](missing.md) and 99 widgets `",
            blank,
            "[good](real.md)",
            blank,
            "There are 12 widgets.",
        ]
    )
    result = verify(content, VerifyContext(project_root=tmp_path, count_sources={"widgets": 12}))
    assert not result.ok and not result.passes()
    assert [(c.kind, c.subject, c.status.value, c.location) for c in result.claims] == [
        ("links", "missing.md", "refuted", "line 3"),
        ("links", "real.md", "verified", "line 5"),
        ("counts", "99", "refuted", "line 3"),
        ("counts", "12", "verified", "line 7"),
    ]
    assert [c.source for c in result.claims if c.kind == "counts"] == ["widgets", "widgets"]


def test_nul_link_does_not_erase_other_refutations(tmp_path):
    content = "[before](before.md) [bad](\x00) [after](after.md)"
    result = verify(content, VerifyContext(project_root=tmp_path))
    assert not result.ok
    assert not result.passes()
    claims = {c.subject: c for c in result.claims}
    assert claims["before.md"].status == ClaimStatus.REFUTED
    assert claims["after.md"].status == ClaimStatus.REFUTED
    assert claims["\x00"].status != ClaimStatus.VERIFIED


def test_large_integer_is_local_error_not_extraction_failure():
    claims = extract_numeric_claims("99 widgets.\n" + "1" * 5000 + " widgets.\n12 widgets.")
    assert len(claims) == 3
    assert [claims[0].value, claims[2].value] == [99, 12]
    assert claims[1].error and claims[1].value == 0
    assert [claim.line for claim in claims] == [1, 2, 3]


@pytest.mark.parametrize("value", [-12, 12, -1234])
def test_numeric_sign_preserved(value):
    text = f"There are {value:,} widgets."
    claims = extract_numeric_claims(text)
    assert len(claims) == 1 and claims[0].value == value
    assert claims[0].offset == text.index(f"{value:,}")


def test_percent_encoding_uses_url_destination_not_first_existing_spelling(tmp_path):
    (tmp_path / "a%20b.md").touch()
    assert not verify("[doc](a%20b.md)", VerifyContext(project_root=tmp_path)).ok
    assert verify("[doc](a%2520b.md)", VerifyContext(project_root=tmp_path)).passes()
    (tmp_path / "a b.md").touch()
    assert verify("[doc](a%20b.md)", VerifyContext(project_root=tmp_path)).passes()


def test_local_query_checks_path(tmp_path):
    (tmp_path / "real.md").touch()
    assert verify("[doc](real.md?raw=true)", VerifyContext(project_root=tmp_path)).passes()


def test_encoded_question_mark_is_path_not_query(tmp_path):
    # A literal percent-encoded spelling must never hide the decoded target.
    (tmp_path / "a%3Fb.md").touch()
    context = VerifyContext(project_root=tmp_path)
    assert not verify("[doc](a%3Fb.md)", context).passes()
    assert verify("[doc](a%253Fb.md)", context).passes()
    if os.name != "nt":
        # Windows cannot create question marks in file names; the rejection
        # above is its correct result for this URL path.
        (tmp_path / "a?b.md").touch()
        assert verify("[doc](a%3Fb.md)", context).passes()


@pytest.mark.parametrize(
    "target",
    [
        "HTTPS://example.com/page",
        "MAILTO:a@example.com",
        "//example.com/page",
        "ftp://example.com/page",
    ],
)
def test_nonlocal_urls_are_unknown_not_refuted(tmp_path, target):
    result = verify(f"[web]({target})", VerifyContext(project_root=tmp_path))
    assert result.ok and not result.passes()
    assert result.claims[0].status == ClaimStatus.UNKNOWN


def test_encoded_absolute_and_traversal_paths_stay_inside_truth_boundary(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (tmp_path / "outside.md").touch()
    observations = []
    check_links(extract_links("[up](%2e%2e/outside.md)"), root, claims=observations)
    assert observations[0].status == ClaimStatus.UNKNOWN


def test_long_unmatched_brackets_do_not_make_links():
    assert extract_links("[" * 100000) == []
