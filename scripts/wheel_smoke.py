"""Smoke-test an exact wheel and sdist in fresh installed environments."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

from release_artifacts import inspect_artifacts


def smoke_artifact(artifact: Path, work: Path, *, rag_extra: bool, expected_version: str) -> dict:
    """Exercise installed APIs and CLI decisions without source-path imports."""
    work.mkdir()
    environment = work / "venv"
    venv.EnvBuilder(with_pip=True, symlinks=os.name != "nt").create(environment)
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    clean_env = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {
            "PYTHONPATH",
            "PYTHONHOME",
            "PYTHONSTARTUP",
            "VIRTUAL_ENV",
            "PIP_TARGET",
            "PIP_PREFIX",
            "PIP_USER",
        }
    }
    clean_env["PYTHONNOUSERSITE"] = "1"
    clean_env["PYTHONIOENCODING"] = "utf-8"
    subprocess.run(
        [str(python), "-I", "-m", "pip", "install", "--no-deps", str(artifact)],
        cwd=work,
        env=clean_env,
        check=True,
        timeout=600,
    )
    checks = []

    def run(name: str, args: list[str], expected: int) -> dict | None:
        result = subprocess.run(
            [str(python), "-I", "-m", "attune_verify", *args],
            cwd=work,
            env=clean_env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
        if result.returncode != expected:
            raise AssertionError(
                f"{artifact.name} {name}: expected {expected}, got {result.returncode}\n"
                f"{result.stderr}\n{result.stdout}"
            )
        if expected == 2 and result.stdout:
            raise AssertionError(f"{name}: invalid input wrote to stdout")
        checks.append({"name": name, "exit": result.returncode})
        return json.loads(result.stdout) if result.stdout.lstrip().startswith("{") else None

    api = subprocess.run(
        [
            str(python),
            "-I",
            "-c",
            (
                "import json, pathlib, sys, attune_verify, importlib.metadata; "
                "from attune_verify import verify, VerifyContext; "
                "package_path=pathlib.Path(attune_verify.__file__); "
                "assert package_path.is_relative_to(pathlib.Path(sys.prefix)); "
                "snippet='```python\\nfrom attune_verify import verify\\n```'; "
                "assert verify(snippet, VerifyContext()).passes(); "
                "print(json.dumps({'python':sys.version,'package_path':str(package_path), "
                "'version':importlib.metadata.version('attune-verify')}))"
            ),
        ],
        cwd=work,
        env=clean_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=120,
    )
    identity = json.loads(api.stdout)
    if identity["version"] != expected_version:
        raise AssertionError("Installed distribution version differs from artifact metadata")
    good = "```python\nfrom attune_verify import verify, VerifyContext\n```"
    documents = {
        "good.md": good,
        "refuted.md": "```python\nfrom attune_verify import MissingExportForReleaseSmoke\n```",
        "unknown.md": "There are 42 widgets.",
        "empty.md": "Ordinary prose without supported claims.",
    }
    for name, content in documents.items():
        (work / name).write_text(content, encoding="utf-8")
    for name, expected in (("good", 0), ("refuted", 1), ("unknown", 1), ("empty", 1)):
        report = run(name, ["check", f"{name}.md", "--format", "json"], expected)
        assert report is not None and report["passed"] == (expected == 0)
    (work / "context.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "help_commands": {"sample": "--verbose"},
                "count_sources": {"tests": 99, "plugins": 12, "widgets": 12},
            }
        ),
        encoding="utf-8",
    )
    maintenance = {
        "eof-import": "[good](good.md)\n```python\nimport absent_release_smoke_package\n",
        "nested-link": "[good](good.md)\n[bad [nested]](absent.md)",
        "exact-flag": "`sample --verbose.extra`",
        "count-source": "Tests: 12\nplugins: 12.",
        "malformed-link-retains-refutation": "[before](before.md) [bad](\x00) [after](after.md)",
        "oversize-number-retains-refutation": (
            "There are 99 widgets.\n\n" + "1" * 5000 + " widgets.\n\nThere are 12 widgets."
        ),
    }
    for name, content in maintenance.items():
        (work / "maintenance.md").write_text(content, encoding="utf-8")
        report = run(
            name, ["check", "maintenance.md", "--context", "context.json", "--format", "json"], 1
        )
        assert report is not None and report["documents"][0]["coverage"]["refuted"] >= 1
        claims = report["documents"][0]["claims"]
        if name == "eof-import":
            assert any(
                claim["kind"] == "imports" and claim["status"] == "refuted" for claim in claims
            )
        elif name == "nested-link":
            assert any(
                claim["subject"] == "absent.md" and claim["status"] == "refuted" for claim in claims
            )
        elif name == "exact-flag":
            assert claims[0]["subject"] == "sample --verbose.extra"
        elif name == "malformed-link-retains-refutation":
            assert any(
                claim["subject"] == "before.md" and claim["status"] == "refuted" for claim in claims
            )
        elif name == "count-source":
            assert [(claim["source"], claim["status"]) for claim in claims] == [
                ("tests", "refuted"),
                ("plugins", "verified"),
            ]
        elif name == "oversize-number-retains-refutation":
            assert [claim["status"] for claim in claims] == ["refuted", "unknown", "verified"]
    run("missing-input", ["check", "missing.md", "--format", "json"], 2)
    run("input-protection", ["check", "good.md", "--output", "good.md"], 2)
    assert (work / "good.md").read_text(encoding="utf-8") == good
    (work / ".git").mkdir()
    config = work / ".git" / "config"
    config.write_text("preserve metadata", encoding="utf-8")
    run("metadata-protection", ["check", "good.md", "--output", ".git/config"], 2)
    if (work / "GOOD.md").exists():
        run("input-case-alias", ["check", "good.md", "--output", "GOOD.md"], 2)
        run("metadata-case-alias", ["check", "good.md", "--output", ".GIT/config"], 2)
        assert (work / "good.md").read_text(encoding="utf-8") == good
    assert config.read_text(encoding="utf-8") == "preserve metadata"
    run("capture", ["receipts", "good.md", "--output", "receipts.json"], 0)
    report = run("unchanged-impact", ["impact", "receipts.json"], 0)
    assert report is not None and not report["needs_recheck"]
    (work / "good.md").write_text(good + "\nChanged document.", encoding="utf-8")
    report = run("changed-impact", ["impact", "receipts.json"], 1)
    assert report is not None and report["needs_recheck"]
    (work / "good.md").write_text(good, encoding="utf-8")
    run("capture-unknown", ["receipts", "empty.md", "--output", "unknown-receipts.json"], 0)
    run("unknown-impact", ["impact", "unknown-receipts.json"], 1)
    (work / "invalid.json").write_text("[" * 2000 + "0" + "]" * 2000, encoding="utf-8")
    run("deep-json", ["evaluate", "invalid.json"], 2)
    (work / "invalid.json").write_text(
        '{"schema_version":1,"cases":[{"id":NaN,"content":"prose"}]}', encoding="utf-8"
    )
    run("nonfinite-json", ["evaluate", "invalid.json"], 2)
    executable = environment / (
        "Scripts/attune-verify.exe" if os.name == "nt" else "bin/attune-verify"
    )
    subprocess.run(
        [str(executable), "check", "good.md"], cwd=work, env=clean_env, check=True, timeout=120
    )
    checks.append({"name": "console-entrypoint", "exit": 0})
    if rag_extra:
        subprocess.run(
            [str(python), "-I", "-m", "pip", "install", f"{artifact}[rag]"],
            cwd=work,
            env=clean_env,
            check=True,
            timeout=600,
        )
        subprocess.run(
            [
                str(python),
                "-I",
                "-c",
                (
                    "import socket; "
                    "message='Network forbidden in factory smoke'; "
                    "deny=lambda *a, **k: (_ for _ in ()).throw(AssertionError(message)); "
                    "socket.create_connection=deny; socket.socket.connect=deny; "
                    "from attune_verify.semantic.rag_adapter import make_rag_judge; "
                    "from attune_verify.semantic.protocol import Judge; "
                    "key='attune-verify-smoke-not-a-real-key'; "
                    "judge=make_rag_judge(auth_mode='api', api_key=key); "
                    "assert isinstance(judge, Judge)"
                ),
            ],
            cwd=work,
            env=clean_env,
            check=True,
            timeout=120,
        )
        checks.append({"name": "rag-factory-no-network", "exit": 0})
    return {"artifact": artifact.name, "passed": True, "identity": identity, "cases": checks}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--sdist", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--check-rag-extra", action="store_true")
    args = parser.parse_args(argv)
    if bool(args.wheel) != bool(args.sdist):
        parser.error("--wheel and --sdist must be supplied together")
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="attune-artifacts-") as directory:
        work = Path(directory)
        dist = work / "dist"
        if args.wheel:
            dist.mkdir()
            for path in (args.wheel, args.sdist):
                shutil.copyfile(path.resolve(), dist / path.name)
        else:
            subprocess.run(
                [sys.executable, "-m", "build", "--no-isolation", "--outdir", str(dist)],
                cwd=root,
                check=True,
                timeout=600,
            )
        metadata = inspect_artifacts(dist)
        checks = [
            smoke_artifact(
                dist / artifact["filename"],
                work / f"installed-{index}",
                rag_extra=args.check_rag_extra,
                expected_version=artifact["version"],
            )
            for index, artifact in enumerate(metadata["artifacts"])
        ]
        if inspect_artifacts(dist) != metadata:
            raise AssertionError("Artifact bytes changed during installed smoke")
        report = {"schema_version": 1, **metadata, "passed": True, "checks": checks}
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(
                json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
            )
        print("Exact installed wheel and sdist API, CLI, receipts, and rejection smoke: passed")


if __name__ == "__main__":
    main()
