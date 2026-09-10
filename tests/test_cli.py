"""Real CLI, manifest, and output-boundary receipts."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from attune_verify import verify
from attune_verify.files import read_text, write_json
from attune_verify.manifest import load_context

SOURCE = str(Path(__file__).resolve().parents[1] / "src")


def run_cli(root, *args):
    if Path(__file__).resolve().parents[1].name == "mutants":
        pytest.skip(
            "mutmut cannot initialize its instrumentation in a temporary CLI cwd; "
            "CLI mutations are covered by test_cli_inprocess"
        )
    return subprocess.run(
        [sys.executable, "-m", "attune_verify", *map(str, args)],
        cwd=root,
        env={**os.environ, "PYTHONPATH": SOURCE},
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_cli_strict_and_legacy_exit_codes(tmp_path):
    (tmp_path / "doc.md").write_text("There are 42 widgets.")
    result = run_cli(tmp_path, "check", "doc.md", "--format", "json")
    assert result.returncode == 1
    assert result.stdout, result.stderr
    report = json.loads(result.stdout)
    assert report["documents"][0]["coverage"]["unknown"] == 1
    assert run_cli(tmp_path, "check", "doc.md", "--policy", "errors").returncode == 0


def test_cli_positive_negative_and_output(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("```python\nfrom pathlib import Path\n```")
    result = run_cli(tmp_path, "check", "doc.md", "--output", "receipt.json")
    assert result.returncode == 0, result.stderr
    assert "1 verified" in result.stdout
    assert json.loads((tmp_path / "receipt.json").read_text())["passed"]
    doc.write_text("```python\nfrom pathlib import NoSuchThing\n```")
    result = run_cli(tmp_path, "check", "doc.md")
    assert result.returncode == 1
    assert "line 2" in result.stdout


def test_cli_empty_and_bad_invocations(tmp_path):
    (tmp_path / "doc.md").write_text("Hello.")
    result = run_cli(tmp_path, "check", "doc.md")
    assert result.returncode == 1
    assert "No supported claims" in result.stdout
    assert run_cli(tmp_path, "check", "missing.md").returncode == 2
    (tmp_path / "invalid.json").write_text("{")
    assert run_cli(tmp_path, "check", "doc.md", "--context", "invalid.json").returncode == 2


def test_manifest_relative_paths_and_live_counts(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    manifest = tmp_path / "context.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project_root": "project",
                "count_sources": {"widgets": {"glob": "*.md"}},
            }
        )
    )
    ctx = load_context(manifest)
    assert ctx.project_root == project
    for index in range(12):
        (project / f"{index}.md").write_text("")
    assert verify("There are 12 widgets.", ctx).passes()
    (project / "0.md").unlink()
    assert not verify("There are 12 widgets.", ctx).ok


def test_cli_links_are_document_relative_and_project_contained(tmp_path):
    nested = tmp_path / "docs"
    nested.mkdir()
    (tmp_path / "root.md").write_text("")
    (nested / "child.md").write_text("[root](../root.md)")
    assert run_cli(tmp_path, "check", "docs/child.md").returncode == 0
    (nested / "child.md").write_text("[outside](../../outside.md)")
    assert run_cli(tmp_path, "check", "docs/child.md").returncode == 1


@pytest.mark.parametrize(
    "extra",
    [
        {"schema_version": 2},
        {"typo": 1},
        {"count_sources": {"widgets": True}},
        {"count_sources": {"widgets": {"glob": "../*"}}},
        {"allowed_help_cmds": "echo"},
        {"help_commands": {"test": 2}},
        {"project_root": 5},
        {"env_python": []},
    ],
)
def test_invalid_manifest_is_rejected(tmp_path, extra):
    path = tmp_path / "context.json"
    path.write_text(json.dumps({"schema_version": 1, **extra}))
    with pytest.raises(ValueError):
        load_context(path)


def test_write_cannot_escape_or_overwrite_metadata(tmp_path):
    with pytest.raises(ValueError):
        write_json(Path("../escaped.json"), {}, root=tmp_path)
    (tmp_path / ".git").mkdir()
    with pytest.raises(ValueError):
        write_json(Path(".git/config"), {}, root=tmp_path)
    with pytest.raises(ValueError):
        write_json(Path("."), {}, root=tmp_path)


def test_report_output_refuses_symlinks(tmp_path):
    target = tmp_path / "target"
    target.write_text("preserve")
    link = tmp_path / "link"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(ValueError):
        write_json(link, {}, root=tmp_path)
    assert target.read_text() == "preserve"


def test_bounded_file_input(tmp_path, monkeypatch):
    import attune_verify.files as files

    monkeypatch.setattr(files, "MAX_INPUT_BYTES", 5)
    path = tmp_path / "large"
    path.write_text("123456")
    with pytest.raises(ValueError, match="exceeds"):
        read_text(path)
    with pytest.raises(ValueError, match="regular"):
        read_text(tmp_path)
