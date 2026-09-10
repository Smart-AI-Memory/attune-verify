"""Real subprocess evidence receipts and hostile receipt boundaries."""

import json
import sys

import pytest

from attune_verify import VerifyContext
from attune_verify.evidence import capture, fingerprint, impact
from tests.test_cli import run_cli


def test_change_removal_and_document_staleness(tmp_path, monkeypatch):
    module = tmp_path / "evidence_fixture.py"
    module.write_text("VALUE = 1\n")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    doc = tmp_path / "guide.md"
    doc.write_text("```python\nfrom evidence_fixture import VALUE\n```")
    ctx = VerifyContext(project_root=tmp_path)
    receipt = capture([doc], ctx)
    assert receipt["documents"][0]["claims"][0]["location"] == "line 2"
    assert not impact(receipt, ctx)["needs_recheck"]
    module.write_text("VALUE = 100\n")
    assert impact(receipt, ctx)["observations"][0]["status"] == "recheck"
    module.unlink()
    assert impact(receipt, ctx)["observations"][0]["status"] == "unknown"
    doc.write_text("Changed document")
    assert impact(receipt, ctx)["observations"][0]["status"] == "document-changed"
    doc.unlink()
    assert impact(receipt, ctx)["needs_recheck"]


def test_receipts_cli_roundtrip(tmp_path):
    doc = tmp_path / "guide.md"
    doc.write_text("```python\nfrom pathlib import Path\n```")
    receipt = tmp_path / "receipt.json"
    result = run_cli(tmp_path, "receipts", str(doc), "--output", str(receipt))
    assert result.returncode == 0, result.stderr
    result = run_cli(tmp_path, "impact", str(receipt))
    assert result.returncode == 0, result.stderr
    assert not json.loads(result.stdout)["needs_recheck"]
    assert run_cli(tmp_path, "receipts", str(doc), "--output", str(doc)).returncode == 2


@pytest.mark.parametrize(
    "content", ["Plain prose", "```python\nimport sys\n```", "```python\nfrom . import thing\n```"]
)
def test_unsupported_receipts_are_unknown(tmp_path, content):
    doc = tmp_path / "guide.md"
    doc.write_text(content)
    ctx = VerifyContext(project_root=tmp_path)
    assert impact(capture([doc], ctx), ctx)["needs_recheck"]


def test_receipt_path_escape_rejected(tmp_path):
    receipt = {
        "schema_version": 1,
        "scope": "python-import-artifacts",
        "documents": [{"file": "../outside", "claims": []}],
    }
    with pytest.raises(ValueError, match="escapes"):
        impact(receipt, VerifyContext(project_root=tmp_path))


@pytest.mark.parametrize(
    "receipt", [{}, {"schema_version": 1, "scope": "python-import-artifacts", "documents": [None]}]
)
def test_invalid_receipt(tmp_path, receipt):
    with pytest.raises(ValueError):
        impact(receipt, VerifyContext(project_root=tmp_path))


def test_invalid_probe_and_missing_interpreter():
    assert "error" in fingerprint("thing;evil()", sys.executable)
    assert "error" in fingerprint("pathlib", "/missing/python")


def test_capture_only_runs_imports(tmp_path):
    class ForbiddenJudge:
        def score(self, *args, **kwargs):
            raise AssertionError("Receipt capture must never call a semantic judge")

    def forbidden_count():
        pytest.fail("Receipt capture must never evaluate count providers")

    doc = tmp_path / "guide.md"
    doc.write_text("```python\nimport pathlib\n```\nThere are 42 widgets.")
    ctx = VerifyContext(
        project_root=tmp_path,
        semantic=True,
        judge=ForbiddenJudge(),
        passages="source",
        count_sources={"widgets": forbidden_count},
    )
    receipt = capture([doc], ctx)
    assert len(receipt["documents"][0]["claims"]) == 1
    assert receipt["scope"] == "python-import-artifacts"
