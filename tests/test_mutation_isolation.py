"""Mutation workers must not share pytest's temporary-directory cleanup."""

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

CONFTEST = Path(__file__).with_name("conftest.py")


def _worker_suite(tmp_path):
    suite = tmp_path / "suite"
    suite.mkdir()
    shutil.copyfile(CONFTEST, suite / "conftest.py")
    (suite / "test_worker.py").write_text(
        textwrap.dedent("""
            import json
            import os
            import time
            from pathlib import Path

            def test_worker(tmp_path, tmp_path_factory):
                receipts = Path(os.environ["WORKER_RECEIPTS"])
                receipt = {
                    "pid": os.getpid(),
                    "base": str(tmp_path_factory.getbasetemp()),
                    "path": str(tmp_path),
                }
                (receipts / f"{os.getpid()}.json").write_text(json.dumps(receipt))
                deadline = time.monotonic() + 20
                while len(list(receipts.glob("*.json"))) < int(os.environ["WORKER_COUNT"]):
                    assert time.monotonic() < deadline, "workers did not run concurrently"
                    time.sleep(0.01)
                marker = tmp_path / "owned.txt"
                marker.write_text(str(os.getpid()))
                assert marker.read_text() == str(os.getpid())
            """),
        encoding="utf-8",
    )
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    env = os.environ.copy()
    env.pop("ATTUNE_MUTATION_TMP_ROOT", None)
    env.pop("PYTEST_ADDOPTS", None)
    env.update(PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", WORKER_RECEIPTS=str(receipts))
    return suite, receipts, env


def _run_workers(suite, env, *, count, args=()):
    env = {**env, "WORKER_COUNT": str(count)}
    processes = []
    results = []
    try:
        for _ in range(count):
            processes.append(
                subprocess.Popen(
                    [sys.executable, "-m", "pytest", "-q", *args],
                    cwd=suite,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            )
        for process in processes:
            stdout, stderr = process.communicate(timeout=30)
            results.append((process.pid, process.returncode, stdout, stderr))
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.communicate()
    return results


def test_four_concurrent_pytest_workers_have_isolated_temp_paths(tmp_path):
    suite, receipts, env = _worker_suite(tmp_path)
    root = tmp_path / "mutation-temp"
    root.mkdir()
    env["ATTUNE_MUTATION_TMP_ROOT"] = str(root)

    results = _run_workers(suite, env, count=4)

    assert all(code == 0 for _, code, _, _ in results), results
    observations = [json.loads(path.read_text()) for path in receipts.glob("*.json")]
    assert {item["pid"] for item in observations} == {pid for pid, _, _, _ in results}
    bases = {Path(item["base"]) for item in observations}
    assert bases == {root / f"worker-{pid}" for pid, _, _, _ in results}
    assert len({item["path"] for item in observations}) == 4
    assert all(Path(item["path"]).parent == Path(item["base"]) for item in observations)
    assert set(root.iterdir()) == bases
    assert not list(root.rglob("pytest-current"))


def test_unset_mutation_root_preserves_explicit_basetemp(tmp_path):
    suite, receipts, env = _worker_suite(tmp_path)
    explicit_base = tmp_path / "explicit-base"

    results = _run_workers(suite, env, count=1, args=("--basetemp", str(explicit_base)))

    assert results[0][1] == 0, results
    receipt = json.loads(next(receipts.glob("*.json")).read_text())
    assert Path(receipt["base"]) == explicit_base
    assert Path(receipt["path"]).parent == explicit_base


@pytest.mark.parametrize("kind", ["relative", "filesystem-root", "missing", "file"])
def test_configured_mutation_root_must_be_an_existing_dedicated_directory(tmp_path, kind):
    suite, _, env = _worker_suite(tmp_path)
    if kind == "relative":
        (suite / "relative").mkdir()
        root = "relative"
    elif kind == "filesystem-root":
        root = tmp_path.anchor
    elif kind == "file":
        path = tmp_path / "file"
        path.write_text("not a directory")
        root = str(path)
    else:
        root = str(tmp_path / "missing")
    env["ATTUNE_MUTATION_TMP_ROOT"] = root

    results = _run_workers(suite, env, count=1)

    assert results[0][1] == pytest.ExitCode.USAGE_ERROR, results
    assert "ATTUNE_MUTATION_TMP_ROOT" in results[0][3]
