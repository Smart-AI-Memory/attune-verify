"""Consumer-facing report fields and declared-source boundaries."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

from attune_verify import VerifyContext, verify
from attune_verify.evaluation import evaluate
from attune_verify.evidence import capture, impact
from attune_verify.files import read_text, write_json
from attune_verify.manifest import load_context


def test_manifest_populates_all_declared_sources(tmp_path):
    path = tmp_path / "context.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "env_python": "./bin/python",
                "help_commands": {"mytool": "usage --verbose"},
                "allowed_help_cmds": ["mytool"],
                "count_sources": {"widgets": 12},
            }
        )
    )
    ctx = load_context(path)
    assert ctx.project_root == tmp_path
    assert ctx.env_python == str(tmp_path / "bin/python")
    assert ctx.help_commands == {"mytool": "usage --verbose"}
    assert ctx.allowed_help_cmds == frozenset({"mytool"})
    assert ctx.count_sources == {"widgets": 12}
    assert verify("There are 12 widgets. `mytool input --verbose`", ctx).passes()
    path.write_text('{"schema_version": 1, "env_python": "python3"}')
    assert load_context(path).env_python == "python3"


@pytest.mark.parametrize(
    "extra",
    [
        {"project_root": "missing"},
        {"count_sources": []},
        {"count_sources": {"": 12}},
        {"count_sources": {"widgets": {"glob": ""}}},
        {"count_sources": {"widgets": {"glob": "/tmp/*"}}},
        {"count_sources": {"widgets": {"glob": r"C:\temp\*"}}},
        {"count_sources": {"widgets": {"glob": r"C:temp\*"}}},
        {"count_sources": {"widgets": {"glob": r"..\*"}}},
        {"count_sources": {"widgets": {"glob": 42}}},
        {"help_commands": {"": ""}},
        {"help_commands": []},
        {"allowed_help_cmds": [""]},
        {"env_python": ""},
    ],
)
def test_manifest_bad_boundaries(tmp_path, extra):
    path = tmp_path / "context.json"
    path.write_text(json.dumps({"schema_version": 1, **extra}))
    with pytest.raises(ValueError):
        load_context(path)


def test_utf8_reports_and_atomic_replacement(tmp_path):
    path = tmp_path / "report.json"
    path.write_text("old")
    payload = {"status": "unknown", "detail": "café 日本語", "coverage": {"unknown": 2}}
    write_json(path, payload, root=tmp_path)
    assert json.loads(read_text(path)) == payload
    assert sorted(p.name for p in tmp_path.iterdir()) == ["report.json"]
    with pytest.raises(ValueError):
        write_json(path, {"score": float("nan")}, root=tmp_path)
    assert json.loads(read_text(path)) == payload


@pytest.mark.parametrize("directory", [".git", ".hg", ".svn"])
def test_all_repository_metadata_is_protected(tmp_path, directory):
    folder = tmp_path / directory
    folder.mkdir()
    target = folder / "config"
    target.write_text("keep")
    with pytest.raises(ValueError, match="metadata"):
        write_json(target, {}, root=tmp_path)
    assert target.read_text() == "keep"


def test_evaluation_confusion_matrix_and_unknowns():
    report = evaluate(
        {
            "schema_version": 1,
            "cases": [
                {
                    "id": "tp",
                    "content": "```python\nfrom pathlib import MissingSymbolForCorpus\n```",
                    "expected_error": True,
                },
                {
                    "id": "fp",
                    "content": "```python\nfrom pathlib import MissingSymbolForCorpus\n```",
                    "expected_error": False,
                },
                {"id": "fn", "content": "There are 42 widgets.", "expected_error": True},
                {"id": "tn", "content": "```python\nimport pathlib\n```", "expected_error": False},
            ],
        },
        VerifyContext(),
    )
    assert report["schema_version"] == 1
    assert report["unit"] == "document error detection"
    assert report["metrics"] == {
        "documents": 4,
        "true_positive": 1,
        "false_positive": 1,
        "false_negative": 1,
        "precision": 0.5,
        "recall": 0.5,
        "abstention_rate": 0.25,
        "unknown_claims": 1,
    }
    assert report["elapsed_seconds"] > 0
    assert report["unlabeled_cases"] == 0
    assert report["human_validated_metrics"] is None
    assert [r["id"] for r in report["cases"]] == ["tp", "fp", "fn", "tn"]
    row = report["cases"][2]
    assert row["unknown_claims"] == row["supported_claims"] == 1
    assert row["status"] == "unknown"
    assert not row["human_heldout"]
    assert row["elapsed_seconds"] > 0


def test_receipt_artifacts_and_report_schema(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    source = tmp_path / "receipt_contract.py"
    source.write_text("ANSWER = 42\n")
    document = tmp_path / "guide.md"
    document.write_text("```python\nfrom receipt_contract import ANSWER\n```")
    ctx = VerifyContext(project_root=tmp_path)
    receipt = capture([document], ctx)
    assert receipt["schema_version"] == 1
    assert receipt["scope"] == "python-import-artifacts"
    saved = receipt["documents"][0]
    assert saved["file"] == "guide.md"
    assert saved["sha256"] == hashlib.sha256(document.read_bytes()).hexdigest()
    claim = saved["claims"][0]
    assert len(claim["id"]) == 64
    assert claim["subject"] == "receipt_contract:ANSWER"
    assert claim["location"] == "line 2"
    assert claim["fingerprint"]["artifacts"] == {
        str(source.resolve()): hashlib.sha256(source.read_bytes()).hexdigest()
    }
    assert claim["fingerprint"]["python"] == sys.version
    assert Path(claim["fingerprint"]["executable"]).resolve() == Path(sys.executable).resolve()
    assert impact(receipt, ctx) == {
        "schema_version": 1,
        "needs_recheck": False,
        "observations": [
            {
                "file": "guide.md",
                "location": "line 2",
                "subject": "receipt_contract:ANSWER",
                "status": "unchanged",
                "detail": "",
            }
        ],
    }
    claim["fingerprint"]["artifacts"] = {"/must/never/be/read": "old fingerprint"}
    report = impact(receipt, ctx)
    assert report["needs_recheck"]
    assert report["observations"][0]["status"] == "recheck"


@pytest.mark.parametrize(
    "document",
    [
        {"file": "a", "claims": None},
        {"file": "a", "claims": [None]},
        {"file": "a", "claims": [{"subject": "pathlib", "fingerprint": None}]},
    ],
)
def test_malformed_receipt_claims(tmp_path, document):
    with pytest.raises(ValueError):
        impact(
            {"schema_version": 1, "scope": "python-import-artifacts", "documents": [document]},
            VerifyContext(project_root=tmp_path),
        )


def test_claim_observations_keep_sources_and_locations(tmp_path):
    (tmp_path / "target.md").write_text("target")
    result = verify(
        "`tool positional --verbose`\n\n[guide](target.md)\n\nThere are 12 widgets.",
        VerifyContext(
            project_root=tmp_path,
            help_commands={"tool": "--verbose"},
            count_sources={"widgets": 12},
        ),
    )
    by_kind = {c.kind: c for c in result.claims}
    assert set(by_kind) == {"flags", "links", "counts"}
    assert by_kind["flags"].location == "line 1"
    assert by_kind["links"].location == "line 3"
    assert by_kind["counts"].location == "line 5"
    assert by_kind["counts"].source == "widgets"
    assert all(c.status == "verified" for c in by_kind.values())


@pytest.mark.parametrize(
    "content,kind,subject,evidence,source",
    [
        (
            "```python\nfrom pathlib import Path\n```",
            "imports",
            "pathlib:Path",
            "from pathlib import Path",
            "interpreter",
        ),
        (
            "```sh\ntool input --verbose\n```",
            "flags",
            "tool --verbose",
            "tool input --verbose",
            "tool",
        ),
        (
            "intro\n`tool input --verbose`",
            "flags",
            "tool --verbose",
            "`tool input --verbose`",
            "tool",
        ),
        ("intro\nThere are 12 widgets.", "counts", "12", "intro\nThere are 12 widgets.", "widgets"),
    ],
)
def test_positive_claim_schema(content, kind, subject, evidence, source):
    ctx = VerifyContext(help_commands={"tool": "--verbose"}, count_sources={"widgets": 12})
    result = verify(content, ctx)
    assert result.passes()
    claim = result.to_dict()["claims"][0]
    assert claim == {
        "id": hashlib.sha256("\0".join((kind, subject, evidence, "line 2")).encode()).hexdigest(),
        "kind": kind,
        "subject": subject,
        "status": "verified",
        "evidence": evidence,
        "location": "line 2",
        "detail": "",
        "source": ctx.env_python if source == "interpreter" else source,
    }


@pytest.mark.parametrize(
    "content", ["Run tool `evil | other --verbose`", "Run tool `evil && other --verbose`"]
)
def test_complex_shell_is_unknown_not_attributed_to_prose(content):
    result = verify(content, VerifyContext(help_commands={"tool": "--verbose"}))
    assert result.status == "unknown"
    assert result.claims[0].subject == "unknown --verbose"
