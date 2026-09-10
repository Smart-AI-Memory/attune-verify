"""In-process CLI assertions complement installed/subprocess boundary receipts."""

import json

import pytest

from attune_verify.cli import main


@pytest.mark.parametrize(
    "content,code",
    [
        ("```python\nfrom pathlib import Path\n```", 0),
        ("```python\nfrom pathlib import AbsentForCLI\n```", 1),
        ("No supported assertions here.", 1),
        ("There are 42 widgets.", 1),
    ],
)
def test_text_and_json(tmp_path, monkeypatch, capsys, content, code):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "doc.md").write_text(content)
    assert main(["check", "doc.md"]) == code
    assert ("PASS" if code == 0 else "FAIL") in capsys.readouterr().out
    assert main(["check", "doc.md", "--format", "json", "--output", "report.json"]) == code
    assert json.loads((tmp_path / "report.json").read_text())["passed"] == (code == 0)


def test_error_and_context(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "context.json").write_text('{"schema_version":1}')
    (tmp_path / "doc.md").write_text("There are 42 widgets.")
    assert main(["check", "doc.md", "--context", "context.json", "--policy", "errors"]) == 0
    assert main(["check", "doc.md", "--output", "doc.md"]) == 2
    assert "overwrite" in capsys.readouterr().err
    assert main(["check", "missing.md"]) == 2


def test_evidence_and_evaluation_commands(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "doc.md").write_text("```python\nimport pathlib\n```")
    assert main(["receipts", "doc.md", "--output", "receipts.json"]) == 0
    assert main(["impact", "receipts.json"]) == 0
    (tmp_path / "doc.md").write_text("changed")
    assert main(["impact", "receipts.json"]) == 1
    (tmp_path / "corpus.json").write_text('{"schema_version":1,"cases":[]}')
    assert main(["evaluate", "corpus.json", "--output", "metrics.json"]) == 0
    assert json.loads((tmp_path / "metrics.json").read_text())["human_validated_metrics"] is None
