"""Release gates bind exact source, distribution bytes, and installed behavior."""

import copy
import importlib.util
import io
import json
import tarfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "release_artifacts", ROOT / "scripts/release_artifacts.py"
)
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)
SHA = "a" * 40
REF = "refs/tags/v0.6.1"


def _runs():
    return [
        {
            "workflowName": name,
            "headSha": SHA,
            "status": "completed",
            "conclusion": "success",
            "databaseId": index,
            "event": "push",
            "headBranch": "main",
        }
        for index, name in enumerate(("tests", "mutation"), 1)
    ]


@pytest.fixture
def dist(tmp_path):
    directory = tmp_path / "dist"
    directory.mkdir()
    _write_pair(directory)
    return directory


def _write_pair(directory, *, wheel_version="0.6.1", sdist_version="0.6.1", name="attune-verify"):
    for file in directory.iterdir():
        file.unlink()
    with zipfile.ZipFile(
        directory / f"attune_verify-{wheel_version}-py3-none-any.whl", "w"
    ) as archive:
        archive.writestr(
            f"attune_verify-{wheel_version}.dist-info/METADATA",
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {wheel_version}\n",
        )
    data = f"Metadata-Version: 2.1\nName: {name}\nVersion: {sdist_version}\n".encode()
    with tarfile.open(directory / f"attune_verify-{sdist_version}.tar.gz", "w:gz") as archive:
        member = tarfile.TarInfo(f"attune_verify-{sdist_version}/PKG-INFO")
        member.size = len(data)
        archive.addfile(member, io.BytesIO(data))


def _evidence(dist):
    metadata = release.inspect_artifacts(dist, REF)
    evidence = {"schema_version": 1, "source_sha": SHA, "ref": REF, "ci_runs": _runs(), **metadata}
    cases = [{"name": name, "exit": code} for name, code in release.SMOKE_EXIT_CODES.items()]
    smoke = {
        "schema_version": 1,
        "passed": True,
        **copy.deepcopy(metadata),
        "checks": [
            {"artifact": artifact["filename"], "passed": True, "cases": copy.deepcopy(cases)}
            for artifact in metadata["artifacts"]
        ],
    }
    return evidence, smoke


def test_artifact_pair_has_bound_version_and_hashes(dist):
    report = release.inspect_artifacts(dist, REF)
    assert report["package"] == "attune-verify"
    assert report["version"] == "0.6.1"
    assert len(report["artifacts"]) == 2
    assert all(len(item["sha256"]) == 64 and item["size"] > 0 for item in report["artifacts"])


@pytest.mark.parametrize("ref", ["refs/heads/main", "v0.6.1", "refs/tags/v0.6.0"])
def test_tag_must_match_package_version(dist, ref):
    with pytest.raises(ValueError, match="Release ref"):
        release.inspect_artifacts(dist, ref)


@pytest.mark.parametrize("change", ["name", "version", "extra", "missing"])
def test_reject_inconsistent_or_ambiguous_distribution(dist, change):
    if change == "name":
        _write_pair(dist, name="some-other-package")
    elif change == "version":
        _write_pair(dist, sdist_version="0.6.0")
    elif change == "extra":
        (dist / "report.json").write_text("{}")
    else:
        next(dist.glob("*.whl")).unlink()
    with pytest.raises(ValueError):
        release.inspect_artifacts(dist, REF)


def test_rejects_duplicate_wheel_metadata(dist):
    with zipfile.ZipFile(next(dist.glob("*.whl")), "a") as archive:
        archive.writestr("other.dist-info/METADATA", "Name: attune-verify\nVersion: 0.6.1\n")
    with pytest.raises(ValueError, match="exactly one METADATA"):
        release.inspect_artifacts(dist, REF)


@pytest.mark.parametrize("change", ["wrong-sha", "running", "failed", "missing", "pr", "branch"])
def test_require_successful_push_checks_on_exact_commit(change):
    runs = _runs()
    if change == "wrong-sha":
        runs[0]["headSha"] = "b" * 40
    elif change == "running":
        runs[0]["status"] = "in_progress"
    elif change == "failed":
        runs[0]["conclusion"] = "failure"
    elif change == "missing":
        runs.pop()
    elif change == "pr":
        runs[0]["event"] = "pull_request"
    else:
        runs[0]["headBranch"] = "feature"
    with pytest.raises(ValueError):
        release.validate_runs(runs, SHA)


def test_latest_attempt_cannot_hide_behind_older_success():
    runs = _runs()
    runs.append({**runs[0], "databaseId": 3, "status": "queued", "conclusion": ""})
    with pytest.raises(ValueError, match="Latest tests"):
        release.validate_runs(runs, SHA)
    runs[-1].update(status="completed", conclusion="success")
    assert release.validate_runs(runs, SHA)[0]["databaseId"] == 3


def test_duplicate_run_ids_cannot_hide_conflicting_statuses():
    runs = _runs()
    runs.append({**runs[0], "conclusion": "failure"})
    with pytest.raises(ValueError, match="duplicate"):
        release.validate_runs(runs, SHA)


@pytest.mark.parametrize("runs", [None, {}, [None], [{"workflowName": "tests"}]])
def test_malformed_run_evidence_fails_closed(runs):
    with pytest.raises(ValueError):
        release.validate_runs(runs, SHA)


def test_artifacts_must_remain_byte_identical(dist):
    evidence, smoke = _evidence(dist)
    release.verify_evidence(dist, evidence, ref=REF, sha=SHA, smoke=smoke)
    with zipfile.ZipFile(next(dist.glob("*.whl")), "a") as archive:
        archive.writestr("new-payload.txt", "artifact changed after smoke")
    with pytest.raises(ValueError, match="artifact evidence mismatch"):
        release.verify_evidence(dist, evidence, ref=REF, sha=SHA, smoke=smoke)


def test_release_can_require_optional_extra_without_a_network_call(dist):
    evidence, smoke = _evidence(dist)
    with pytest.raises(ValueError, match="rag extra"):
        release.verify_evidence(
            dist, evidence, ref=REF, sha=SHA, smoke=smoke, require_rag_extra=True
        )
    for check in smoke["checks"]:
        check["cases"].append({"name": "rag-factory-no-network", "exit": 0})
    release.verify_evidence(dist, evidence, ref=REF, sha=SHA, smoke=smoke, require_rag_extra=True)


@pytest.mark.parametrize(
    "change",
    [
        "schema",
        "sha",
        "ref",
        "smoke-schema",
        "smoke-hash",
        "smoke-failed",
        "missing-sdist",
        "missing-negative",
        "wrong-exit",
    ],
)
def test_release_evidence_schema_and_behavior_are_required(dist, change):
    evidence, smoke = _evidence(dist)
    if change == "schema":
        evidence["schema_version"] = True
    elif change == "sha":
        evidence["source_sha"] = "b" * 40
    elif change == "ref":
        evidence["ref"] = "refs/heads/main"
    elif change == "smoke-schema":
        smoke["schema_version"] = True
    elif change == "smoke-hash":
        smoke["artifacts"][0]["sha256"] = "0" * 64
    elif change == "smoke-failed":
        smoke["passed"] = False
    elif change == "missing-sdist":
        smoke["checks"].pop()
    elif change == "missing-negative":
        smoke["checks"][0]["cases"] = [{"name": "good", "exit": 0}]
    else:
        smoke["checks"][0]["cases"][1]["exit"] = 0
    with pytest.raises(ValueError):
        release.verify_evidence(dist, evidence, ref=REF, sha=SHA, smoke=smoke)


def test_cli_records_then_verifies_and_rejects_changes(dist, tmp_path):
    runs_file = tmp_path / "runs.json"
    runs_file.write_text(json.dumps(_runs()), encoding="utf-8")
    report = tmp_path / "evidence" / "release.json"
    args = ["--dist", str(dist), "--ref", REF, "--sha", SHA, "--report", str(report)]
    assert release.main([*args, "--runs", str(runs_file)]) == 0
    _, smoke = _evidence(dist)
    smoke_file = tmp_path / "smoke.json"
    smoke_file.write_text(json.dumps(smoke), encoding="utf-8")
    assert release.main([*args, "--verify", "--smoke", str(smoke_file)]) == 0
    assert (
        release.main([*args, "--ref", "refs/heads/main", "--verify", "--smoke", str(smoke_file)])
        == 1
    )


def test_publish_workflow_tests_before_upload_and_verifies_after_download():
    text = (ROOT / ".github/workflows/publish-pypi.yml").read_text()
    assert '--commit "$GITHUB_SHA" --branch main --event push' in text
    assert "workflowName,headSha,status,conclusion,databaseId,event,headBranch" in text
    assert text.count("python -m build --no-isolation") == 1
    assert text.index("--check-runs-only") < text.index("python -m build --no-isolation")
    assert text.index("scripts/wheel_smoke.py") < text.index("name: Upload artifacts")
    assert text.index("name: Download release evidence") < text.rindex(
        "scripts/release_artifacts.py --verify"
    )
    assert text.rindex("scripts/release_artifacts.py --verify") < text.rindex(
        "name: Publish to PyPI"
    )
    assert "environment: pypi" in text and "needs: build" in text
    assert "name: release-evidence" in text
    assert text.count("--require-rag-extra") == 2


def test_ci_smokes_existing_pair_and_optional_extra():
    text = (ROOT / ".github/workflows/tests.yml").read_text()
    assert text.count("python -m build --no-isolation") == 1
    assert "--wheel dist/*.whl --sdist dist/*.tar.gz" in text
    assert "--check-rag-extra" in text
