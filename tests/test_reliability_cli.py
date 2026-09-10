"""Regressions for file identity, declared commands, and strict JSON reports."""

import json
import os

import pytest

from attune_verify import VerifyContext
from attune_verify.cli import main
from attune_verify.evaluation import evaluate
from attune_verify.files import write_json
from attune_verify.manifest import load_context


@pytest.mark.parametrize("command", ["check", "receipts", "evaluate"])
def test_output_case_alias_preserves_input(tmp_path, monkeypatch, capsys, command):
    monkeypatch.chdir(tmp_path)
    filename = "doc.json" if command == "evaluate" else "doc.md"
    original = (
        '{"schema_version":1,"cases":[]}'
        if command == "evaluate"
        else "```python\nfrom pathlib import Path\n```"
    )
    document = tmp_path / filename
    document.write_text(original, encoding="utf-8")
    if not (tmp_path / filename.upper()).exists():
        pytest.skip("filesystem is case-sensitive")
    assert main([command, filename, "--output", filename.upper()]) == 2
    assert document.read_text(encoding="utf-8") == original
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "overwrite" in captured.err


def test_output_case_alias_preserves_context(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    manifest = tmp_path / "context.json"
    original = '{"schema_version":1}'
    manifest.write_text(original, encoding="utf-8")
    if not (tmp_path / "CONTEXT.json").exists():
        pytest.skip("filesystem is case-sensitive")
    (tmp_path / "doc.md").write_text("```python\nimport pathlib\n```", encoding="utf-8")
    assert main(["check", "doc.md", "--context", "context.json", "--output", "CONTEXT.json"]) == 2
    assert manifest.read_text(encoding="utf-8") == original
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("metadata", [".git", ".hg", ".svn"])
def test_metadata_case_alias_is_rejected(tmp_path, metadata):
    folder = tmp_path / metadata
    folder.mkdir()
    target = folder / "config"
    target.write_text("preserve metadata", encoding="utf-8")
    if not (tmp_path / metadata.upper()).exists():
        pytest.skip("filesystem is case-sensitive")
    with pytest.raises(ValueError, match="metadata"):
        write_json(tmp_path / metadata.upper() / "config", {}, root=tmp_path)
    assert target.read_text(encoding="utf-8") == "preserve metadata"


@pytest.mark.skipif(os.name == "nt", reason="POSIX executable fixtures")
def test_manifest_command_authority_is_independent_of_cwd(tmp_path, monkeypatch, capsys):
    declared = tmp_path / "declared"
    calling = tmp_path / "calling"
    for directory, flag in ((declared, "--declared"), (calling, "--wrong")):
        directory.mkdir()
        tool = directory / "tool"
        tool.write_text(f"#!/bin/sh\nprintf '%s\\n' '{flag}'\n", encoding="utf-8")
        tool.chmod(0o700)
    manifest = declared / "context.json"
    manifest.write_text(
        json.dumps({"schema_version": 1, "allowed_help_cmds": ["./tool"]}), encoding="utf-8"
    )
    document = declared / "doc.md"
    document.write_text("`./tool --wrong`", encoding="utf-8")
    args = ["check", str(document), "--context", str(manifest), "--format", "json"]
    for directory in (declared, calling):
        monkeypatch.chdir(directory)
        assert main(args) == 1
        claim = json.loads(capsys.readouterr().out)["documents"][0]["claims"][0]
        assert claim["status"] == "refuted"
        assert claim["source"] == str(declared / "tool")
    document.write_text("`./tool --declared`", encoding="utf-8")
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["passed"]


@pytest.mark.parametrize("command", ["evaluate", "impact", "context"])
@pytest.mark.parametrize("invalid", ["NaN", "Infinity", "-Infinity", "1e999", "deep"])
def test_invalid_json_is_quiet_and_preserves_output(
    tmp_path, monkeypatch, capsys, command, invalid
):
    monkeypatch.chdir(tmp_path)
    document = tmp_path / "doc.md"
    document.write_text("```python\nimport pathlib\n```", encoding="utf-8")
    filename = tmp_path / "input.json"
    payload = "[" * 2000 + "0" + "]" * 2000 if invalid == "deep" else invalid
    if invalid != "deep":
        if command == "evaluate":
            payload = '{"schema_version":1,"cases":[{"content":"prose","id":' + payload + "}]}"
        elif command == "context":
            payload = '{"schema_version":1,"ignored":' + payload + "}"
    filename.write_text(payload, encoding="utf-8")
    output = tmp_path / "report.json"
    output.write_text("preserve old report", encoding="utf-8")
    args = (
        ["check", str(document), "--context", str(filename)]
        if command == "context"
        else [command, str(filename)]
    )
    for output_args in ([], ["--output", str(output)]):
        assert main([*args, *output_args]) == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "attune-verify:" in captured.err
        assert "Traceback" not in captured.err
        assert output.read_text(encoding="utf-8") == "preserve old report"


@pytest.mark.parametrize("identifier", [1, True, [], {}, float("nan")])
def test_evaluation_rejects_nonstring_ids(identifier):
    with pytest.raises(ValueError, match="id"):
        evaluate(
            {"schema_version": 1, "cases": [{"id": identifier, "content": "plain prose"}]},
            VerifyContext(),
        )


@pytest.mark.parametrize("identifier", [None, "case-1", "café"])
def test_evaluation_retains_supported_ids(identifier):
    report = evaluate(
        {"schema_version": 1, "cases": [{"id": identifier, "content": "plain prose"}]},
        VerifyContext(),
    )
    assert report["cases"][0]["id"] == identifier


def test_json_stdout_and_file_are_identical(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "corpus.json").write_text(
        json.dumps({"schema_version": 1, "cases": [{"id": "café", "content": "plain prose"}]}),
        encoding="utf-8",
    )
    assert main(["evaluate", "corpus.json", "--output", "report.json"]) == 0
    assert capsys.readouterr().out == (tmp_path / "report.json").read_text(encoding="utf-8")


def test_reports_roundtrip_on_ascii_streams():
    from attune_verify.files import json_text

    payload = {"document": "日本語.md", "detail": "café"}
    serialized = json_text(payload)
    assert json.loads(serialized.encode("ascii")) == payload


def test_deep_report_serialization_respects_native_limits(tmp_path):
    target = tmp_path / "report.json"
    target.write_text("preserve report", encoding="utf-8")
    value = []
    for _ in range(2000):
        value = [value]
    try:
        serialized = json.dumps(value, indent=2, ensure_ascii=True, allow_nan=False)
    except RecursionError:
        with pytest.raises(ValueError, match="nesting"):
            write_json(target, value, root=tmp_path)
        assert target.read_text(encoding="utf-8") == "preserve report"
    else:
        write_json(target, value, root=tmp_path)
        assert target.read_text(encoding="utf-8") == serialized + "\n"
    assert list(tmp_path.iterdir()) == [target]


def test_report_recursion_failure_preserves_existing_file(tmp_path, monkeypatch):
    import attune_verify.files as files

    target = tmp_path / "report.json"
    target.write_text("preserve report", encoding="utf-8")

    def fail_serialization(*args, **kwargs):
        raise RecursionError("injected serializer recursion limit")

    monkeypatch.setattr(files.json, "dumps", fail_serialization)
    with pytest.raises(ValueError, match="nesting"):
        write_json(target, {"normal": "value"}, root=tmp_path)
    assert target.read_text(encoding="utf-8") == "preserve report"
    assert list(tmp_path.iterdir()) == [target]


def test_manifest_configures_probe_limits_without_rewriting_aliases(tmp_path):
    manifest = tmp_path / "context.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "allowed_help_cmds": ["./bin/tool", "bare-tool"],
                "max_probe_attempts": 5,
                "probe_timeout_seconds": 0.75,
                "max_probe_output_bytes": 2048,
            }
        ),
        encoding="utf-8",
    )
    ctx = load_context(manifest)
    assert ctx.allowed_help_cmds == frozenset({"./bin/tool", "bare-tool"})
    assert ctx.help_executables == {"./bin/tool": str(tmp_path / "bin" / "tool")}
    assert ctx.max_probe_attempts == 5
    assert ctx.probe_timeout_seconds == 0.75
    assert ctx.max_probe_output_bytes == 2048


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_probe_attempts", True),
        ("max_probe_attempts", 0),
        ("max_probe_attempts", 1.5),
        ("max_probe_output_bytes", -1),
        ("max_probe_output_bytes", "2048"),
        ("probe_timeout_seconds", False),
        ("probe_timeout_seconds", -0.1),
        ("probe_timeout_seconds", "1"),
    ],
)
def test_invalid_probe_limits_are_rejected(tmp_path, field, value):
    manifest = tmp_path / "context.json"
    manifest.write_text(json.dumps({"schema_version": 1, field: value}), encoding="utf-8")
    with pytest.raises(ValueError, match=field):
        load_context(manifest)
