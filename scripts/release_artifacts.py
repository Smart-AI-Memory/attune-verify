"""Bind release metadata, CI results, smoke evidence, and distribution bytes."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tarfile
import zipfile
from email.parser import BytesParser
from pathlib import Path

SMOKE_EXIT_CODES = {
    "good": 0,
    "refuted": 1,
    "unknown": 1,
    "empty": 1,
    "missing-input": 2,
    "input-protection": 2,
    "metadata-protection": 2,
    "capture": 0,
    "unchanged-impact": 0,
    "changed-impact": 1,
    "capture-unknown": 0,
    "unknown-impact": 1,
    "deep-json": 2,
    "nonfinite-json": 2,
    "console-entrypoint": 0,
    "eof-import": 1,
    "nested-link": 1,
    "exact-flag": 1,
    "count-source": 1,
    "malformed-link-retains-refutation": 1,
    "oversize-number-retains-refutation": 1,
}


def _metadata(data: bytes) -> tuple[str, str]:
    message = BytesParser().parsebytes(data)
    if len(message.get_all("Name", [])) != 1 or len(message.get_all("Version", [])) != 1:
        raise ValueError("Artifact must have exactly one package name and version")
    name, version = str(message["Name"]), str(message["Version"])
    if re.sub(r"[-_.]+", "-", name).lower() != "attune-verify":
        raise ValueError(f"Unexpected package name: {name}")
    if not version or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.!+_-]*", version):
        raise ValueError("Invalid artifact version")
    return "attune-verify", version


def inspect_artifacts(dist: Path, ref: str | None = None) -> dict:
    """Inspect exactly one wheel and one sdist without extracting either."""
    paths = sorted(dist.iterdir())
    wheels = [path for path in paths if path.name.endswith(".whl")]
    sdists = [path for path in paths if path.name.endswith(".tar.gz")]
    if len(paths) != 2 or len(wheels) != 1 or len(sdists) != 1:
        raise ValueError("Distribution directory must contain exactly one wheel and one sdist")
    artifacts = []
    for path in paths:
        if not path.is_file() or path.is_symlink():
            raise ValueError("Artifacts must be regular, non-symlink files")
        if path in wheels:
            with zipfile.ZipFile(path) as archive:
                members = [
                    name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
                ]
                if len(members) != 1:
                    raise ValueError("Wheel must contain exactly one METADATA file")
                with archive.open(members[0]) as stream:
                    metadata = stream.read(1024 * 1024 + 1)
        else:
            with tarfile.open(path, "r:gz") as archive:
                members = [
                    m
                    for m in archive.getmembers()
                    if len(Path(m.name).parts) == 2 and m.name.endswith("/PKG-INFO")
                ]
                if len(members) != 1 or not members[0].isfile():
                    raise ValueError("Sdist must contain one top-level regular PKG-INFO file")
                stream = archive.extractfile(members[0])
                if stream is None:
                    raise ValueError("Sdist PKG-INFO is unreadable")
                with stream:
                    metadata = stream.read(1024 * 1024 + 1)
        if len(metadata) > 1024 * 1024:
            raise ValueError("Artifact metadata is too large")
        name, version = _metadata(metadata)
        artifacts.append(
            {
                "filename": path.name,
                "package": name,
                "version": version,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "size": path.stat().st_size,
            }
        )
    versions = {artifact["version"] for artifact in artifacts}
    if len(versions) != 1:
        raise ValueError("Wheel and sdist versions differ")
    version = versions.pop()
    if ref is not None and ref != f"refs/tags/v{version}":
        raise ValueError(f"Release ref must be refs/tags/v{version}")
    return {"package": "attune-verify", "version": version, "artifacts": artifacts}


def validate_runs(runs: object, sha: str) -> list[dict]:
    """Require the newest tests and mutation runs for the exact full commit."""
    if not re.fullmatch(r"[0-9a-f]{40}", sha) or not isinstance(runs, list):
        raise ValueError("CI evidence requires a full commit SHA and a run list")
    for run in runs:
        if (
            not isinstance(run, dict)
            or not isinstance(run.get("workflowName"), str)
            or not isinstance(run.get("headSha"), str)
            or not isinstance(run.get("status"), str)
            or not isinstance(run.get("event"), str)
            or not isinstance(run.get("headBranch"), str)
            or (run.get("conclusion") is not None and not isinstance(run.get("conclusion"), str))
            or type(run.get("databaseId")) is not int
            or run["databaseId"] <= 0
        ):
            raise ValueError("Malformed CI run evidence")
    if len({run["databaseId"] for run in runs}) != len(runs):
        raise ValueError("CI run evidence contains duplicate run IDs")
    selected = []
    for workflow in ("tests", "mutation"):
        candidates = [
            run
            for run in runs
            if run["workflowName"] == workflow
            and run["headSha"] == sha
            and run["event"] == "push"
            and run["headBranch"] == "main"
        ]
        if not candidates:
            raise ValueError(f"No {workflow} run for exact commit {sha}")
        latest = max(candidates, key=lambda run: run["databaseId"])
        if latest["status"] != "completed" or latest["conclusion"] != "success":
            raise ValueError(f"Latest {workflow} run for {sha} has not completed successfully")
        selected.append(latest)
    return selected


def verify_evidence(
    dist: Path,
    evidence: object,
    *,
    ref: str,
    sha: str,
    smoke: object,
    require_rag_extra: bool = False,
) -> None:
    """Refuse changed distributions or smoke results from different bytes."""
    if not isinstance(evidence, dict) or type(evidence.get("schema_version")) is not int:
        raise ValueError("Invalid release evidence schema")
    if evidence["schema_version"] != 1 or evidence.get("source_sha") != sha:
        raise ValueError("Release evidence commit does not match")
    if evidence.get("ref") != ref:
        raise ValueError("Release evidence ref does not match")
    current = inspect_artifacts(dist, ref)
    for field in ("package", "version", "artifacts"):
        if evidence.get(field) != current[field]:
            raise ValueError(f"Release artifact evidence mismatch: {field}")
    validate_runs(evidence.get("ci_runs"), sha)
    if (
        not isinstance(smoke, dict)
        or type(smoke.get("schema_version")) is not int
        or smoke["schema_version"] != 1
        or smoke.get("passed") is not True
        or smoke.get("artifacts") != current["artifacts"]
        or not isinstance(smoke.get("checks"), list)
    ):
        raise ValueError("Installed smoke evidence does not match release artifacts")
    checks = smoke["checks"]
    expected = {artifact["filename"] for artifact in current["artifacts"]}
    if (
        len(checks) != len(expected)
        or any(
            not isinstance(check, dict)
            or check.get("passed") is not True
            or not isinstance(check.get("artifact"), str)
            for check in checks
        )
        or {check.get("artifact") for check in checks} != expected
    ):
        raise ValueError("Installed smoke must pass for both wheel and sdist")
    for check in checks:
        cases = check.get("cases")
        if not isinstance(cases, list) or any(
            not isinstance(case, dict)
            or not isinstance(case.get("name"), str)
            or type(case.get("exit")) is not int
            for case in cases
        ):
            raise ValueError("Invalid installed smoke case schema")
        outcomes = {case["name"]: case["exit"] for case in cases}
        if len(outcomes) != len(cases) or any(
            outcomes.get(name) != code for name, code in SMOKE_EXIT_CODES.items()
        ):
            raise ValueError("Installed smoke is missing required behavioral evidence")
        if require_rag_extra and outcomes.get("rag-factory-no-network") != 0:
            raise ValueError("Installed smoke must validate the rag extra factory")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--runs", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--smoke", type=Path)
    parser.add_argument("--check-runs-only", action="store_true")
    parser.add_argument("--require-rag-extra", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.verify:
            if args.smoke is None:
                raise ValueError("--verify requires --smoke")
            verify_evidence(
                args.dist,
                json.loads(args.report.read_text(encoding="utf-8")),
                ref=args.ref,
                sha=args.sha,
                smoke=json.loads(args.smoke.read_text(encoding="utf-8")),
                require_rag_extra=args.require_rag_extra,
            )
        else:
            if args.runs is None:
                raise ValueError("Recording evidence requires --runs")
            ci_runs = validate_runs(json.loads(args.runs.read_text(encoding="utf-8")), args.sha)
            if args.check_runs_only:
                if not re.fullmatch(r"refs/tags/v[^/]+", args.ref):
                    raise ValueError("A version tag ref is required")
            else:
                report = {
                    "schema_version": 1,
                    "source_sha": args.sha,
                    "ref": args.ref,
                    "ci_runs": ci_runs,
                    **inspect_artifacts(args.dist, args.ref),
                }
                args.report.parent.mkdir(parents=True, exist_ok=True)
                args.report.write_text(
                    json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
                )
        print("Release artifact and exact-commit evidence: passed")
        return 0
    except (OSError, ValueError, TypeError, KeyError, tarfile.TarError, zipfile.BadZipFile) as exc:
        print(f"Release evidence rejected: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
