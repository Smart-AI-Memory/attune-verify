"""Tests for the data model (T2)."""
import pytest
from attune_verify.result import (
    Finding,
    FindingKind,
    VerificationError,
    VerifyResult,
    raise_if_failed,
)


def test_finding_frozen():
    f = Finding(kind=FindingKind.DEAD_LINK, detail="test", evidence="x")
    with pytest.raises(Exception):
        object.__setattr__(f, "detail", "mutated")


def test_verify_result_ok_no_errors():
    r = VerifyResult(findings=[
        Finding(kind=FindingKind.DEAD_LINK, detail="w", evidence="x", severity="warning")
    ])
    assert r.ok is True


def test_verify_result_not_ok_with_error():
    r = VerifyResult(findings=[
        Finding(kind=FindingKind.DEAD_LINK, detail="e", evidence="x", severity="error")
    ])
    assert r.ok is False


def test_raise_if_failed_raises_on_error():
    r = VerifyResult(findings=[
        Finding(kind=FindingKind.DEAD_LINK, detail="e", evidence="x", severity="error")
    ])
    with pytest.raises(VerificationError) as exc_info:
        raise_if_failed(r)
    assert exc_info.value.result is r


def test_raise_if_failed_no_raise_on_ok():
    r = VerifyResult()
    raise_if_failed(r)
