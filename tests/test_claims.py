"""Claim coverage, unknowns, and compatibility at the public boundary."""

import json

import pytest

from attune_verify import (
    ClaimStatus,
    VerificationError,
    VerificationPolicy,
    VerifyContext,
    raise_if_failed,
    verify,
)


def test_report_counts_mixed_claims(tmp_path):
    (tmp_path / "real.md").write_text("text")
    result = verify(
        "```python\nfrom pathlib import Path\n```\n"
        "[real](real.md) [bad](absent.md) [web](https://example.com)\n"
        "There are 99 widgets.",
        VerifyContext(project_root=tmp_path),
    )
    assert result.coverage == {"total": 5, "verified": 2, "refuted": 1, "unknown": 2}
    assert result.status == ClaimStatus.REFUTED
    report = json.loads(json.dumps(result.to_dict()))
    assert len({c["id"] for c in report["claims"]}) == 5
    assert report["schema_version"] == 1


@pytest.mark.parametrize(
    "content,context",
    [
        ("ordinary prose", VerifyContext()),
        ("There are 42 widgets.", VerifyContext()),
        ("`unknown --madeup`", VerifyContext()),
        ("```python\nfrom .local import thing\n```", VerifyContext()),
        ("```python\nfrom os import *\n```", VerifyContext()),
        ("[web](https://example.com)", VerifyContext()),
        ("[heading](#missing)", VerifyContext()),
        ("claim", VerifyContext(semantic=True)),
    ],
)
def test_legacy_ok_does_not_imply_strict_pass(content, context):
    result = verify(content, context)
    assert result.ok
    raise_if_failed(result)  # existing API remains error-only
    assert result.status == ClaimStatus.UNKNOWN
    assert not result.passes()
    with pytest.raises(VerificationError):
        raise_if_failed(result, VerificationPolicy())


def test_policy_requires_requested_kinds():
    result = verify("```python\nimport os\n```", VerifyContext())
    assert result.passes()
    assert not result.passes(VerificationPolicy(required_kinds=("counts",)))


def test_infrastructure_failure_is_unknown():
    result = verify("```python\nimport os\n```", VerifyContext(env_python="/no/such/python"))
    assert result.ok
    assert result.coverage["unknown"] == 1
    assert not result.passes()


def test_ambiguous_count_bindings_are_unknown():
    result = verify(
        "There are 10 tests.", VerifyContext(count_sources={"tests": 10, "unit tests": 12})
    )
    assert result.ok
    assert result.coverage["unknown"] == 1


def test_bad_source_does_not_hide_other_counts():
    def broken():
        raise RuntimeError("source unavailable")

    result = verify(
        "There are 10 tests and 12 widgets.",
        VerifyContext(count_sources={"tests": broken, "widgets": 12}),
    )
    assert result.coverage["verified"] == 1
    assert result.coverage["unknown"] == 1


def test_literal_code_numbers_are_not_count_claims():
    result = verify("Use `--timeout 30` or:\n```sh\ncmd --timeout 40\n```", VerifyContext())
    assert not [c for c in result.claims if c.kind == "counts"]


def test_symbol_aliases_and_child_modules():
    result = verify(
        "```python\nfrom pathlib import Path as P\nfrom email import mime\n```", VerifyContext()
    )
    assert result.passes(), result.findings
    assert {c.subject for c in result.claims} == {"pathlib:Path", "email:mime"}


def test_import_statement_line_is_precise():
    result = verify(
        "intro\n```python\nimport os\nfrom pathlib import NothingHere\n```", VerifyContext()
    )
    assert result.findings[0].location == "line 4"


def test_checker_failure_prevents_strict_pass(monkeypatch):
    from importlib import import_module

    module = import_module("attune_verify._verify")

    def broken(content, context):
        raise RuntimeError("unavailable")

    monkeypatch.setattr(module, "_check_flags", broken)
    result = verify("```python\nimport os\n```", VerifyContext())
    assert result.coverage["verified"] == 1
    assert not result.passes()
