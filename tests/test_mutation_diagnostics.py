"""Interrupted mutation runs retain diagnostic evidence and cannot pass the gate."""

import json
import os
import shlex
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_mutation.py"
WORKFLOW = ROOT / ".github" / "workflows" / "mutation.yml"
POSIX_ONLY = pytest.mark.skipif(os.name != "posix", reason="mutation CI runs on Linux")
WORKER_NAME = "mutmut: example.x_work__mutmut_2"


def _step(name):
    return (
        WORKFLOW.read_text(encoding="utf-8")
        .split(f"      - name: {name}\n", 1)[1]
        .split("      - name:", 1)[0]
    )


def _fake_mutmut(tmp_path, *, exit_code=7, blocking=False):
    executable = tmp_path / "bin" / "mutmut"
    executable.parent.mkdir()
    script = tmp_path / "fake_mutmut.py"
    script.write_text(
        textwrap.dedent(f"""
            import json
            import os
            import subprocess
            import sys
            import time
            from pathlib import Path

            if sys.argv[1:] == ["export-cicd-stats"]:
                os.execv(sys.executable, [sys.executable, "-m", "mutmut", *sys.argv[1:]])
            assert sys.argv[1:] == ["run", "--max-children", "4"], sys.argv
            metadata = Path("mutants/src/example.py.meta")
            metadata.parent.mkdir(parents=True)
            metadata.write_text(json.dumps({{
                "exit_code_by_key": {{"example.x_work__mutmut_1": 1,
                                     "example.x_work__mutmut_2": None}},
                "durations_by_key": {{"example.x_work__mutmut_1": 0.1}},
                "estimated_durations_by_key": {{"example.x_work__mutmut_2": 0.1}},
            }}))
            Path("mutants/mutmut-stats.json").write_text('{{"fixture": "baseline stats"}}')
            if {blocking!r}:
                worker = subprocess.Popen([
                    sys.executable, "-c", "import time; time.sleep(60)", {WORKER_NAME!r}
                ])
                Path("worker.pid").write_text(str(worker.pid))
                worker.wait()
            time.sleep(0.1)
            sys.exit({exit_code!r})
            """),
        encoding="utf-8",
    )
    executable.write_text(
        f'#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(script))} "$@"\n',
        encoding="utf-8",
    )
    executable.chmod(0o755)
    source = tmp_path / "src" / "example.py"
    source.parent.mkdir()
    source.write_text("def work():\n    return 1\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[tool.mutmut]\nsource_paths = ["src/"]\n', encoding="utf-8"
    )
    return {**os.environ, "PATH": str(executable.parent) + os.pathsep + os.environ["PATH"]}


def _snapshots(tmp_path):
    path = tmp_path / "mutation-diagnostics" / "workers.jsonl"
    if not path.exists():
        return []
    snapshots = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            snapshots.append(json.loads(line))
        except json.JSONDecodeError:
            pass  # The wrapper may be appending its next snapshot.
    return snapshots


@POSIX_ONLY
@pytest.mark.parametrize("exit_code", [0, 7])
def test_mutation_wrapper_preserves_command_exit_and_raw_evidence(tmp_path, exit_code):
    env = _fake_mutmut(tmp_path, exit_code=exit_code)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--interval", "0.02"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == exit_code, result.stderr
    status = json.loads((tmp_path / "mutation-diagnostics" / "run-status.json").read_text())
    assert status["command"] == ["mutmut", "run", "--max-children", "4"]
    assert status["exit_code"] == exit_code
    assert status["interrupted_signal"] is None
    assert (tmp_path / "mutants" / "src" / "example.py.meta").is_file()
    assert (tmp_path / "mutants" / "mutmut-stats.json").is_file()
    processes = [process for item in _snapshots(tmp_path) for process in item["processes"]]
    assert processes
    assert all(
        {"pid", "ppid", "elapsed", "cpu_percent", "rss_kib", "state", "command"} <= process.keys()
        for process in processes
    )


@POSIX_ONLY
@pytest.mark.parametrize("interrupt_signal", [signal.SIGINT, signal.SIGTERM])
def test_interrupted_partial_run_retains_active_worker_diagnostics(tmp_path, interrupt_signal):
    env = _fake_mutmut(tmp_path, blocking=True)
    process = subprocess.Popen(
        [sys.executable, str(SCRIPT), "--interval", "0.02"],
        cwd=tmp_path,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            snapshots = _snapshots(tmp_path)
            if any(
                WORKER_NAME in item["command"]
                for snapshot in snapshots
                for item in snapshot["processes"]
            ):
                break
            assert process.poll() is None, process.communicate()
            time.sleep(0.02)
        else:
            pytest.fail("active mutation worker was not observed")
        metadata = tmp_path / "mutants" / "src" / "example.py.meta"
        original_metadata = metadata.read_bytes()
        process.send_signal(interrupt_signal)
        stdout, stderr = process.communicate(timeout=10)

        assert process.returncode == 128 + interrupt_signal, (stdout, stderr)
        assert metadata.read_bytes() == original_metadata
        status = json.loads((tmp_path / "mutation-diagnostics" / "run-status.json").read_text())
        assert status["interrupted_signal"] == interrupt_signal
        assert status["exit_code"] == 128 + interrupt_signal
        worker = next(
            item
            for snapshot in snapshots
            for item in snapshot["processes"]
            if WORKER_NAME in item["command"]
        )
        assert worker["rss_kib"] > 0
        assert worker["elapsed"]
        assert worker["cpu_percent"] >= 0
        assert worker["state"]
        assert WORKER_NAME in stdout
        worker_state = subprocess.run(
            ["ps", "-p", str(worker["pid"]), "-o", "stat="],
            capture_output=True,
            text=True,
            check=False,
        )
        assert not worker_state.stdout.strip() or worker_state.stdout.strip().startswith("Z")
    finally:
        if process.poll() is None:
            process.terminate()
            process.communicate(timeout=10)


@POSIX_ONLY
def test_failed_run_exports_actual_partial_metadata_and_gate_rejects_it(tmp_path):
    pytest.importorskip("mutmut")
    env = _fake_mutmut(tmp_path)
    run = subprocess.run(
        [sys.executable, str(SCRIPT)], cwd=tmp_path, env=env, capture_output=True, timeout=10
    )
    assert run.returncode == 7
    metadata = tmp_path / "mutants" / "src" / "example.py.meta"
    original_metadata = metadata.read_bytes()
    export_step = _step("Export mutation evidence")
    assert "if: always()" in export_step
    export_script = textwrap.dedent(export_step.split("        run: |\n", 1)[1])

    export = subprocess.run(
        ["/bin/bash", "-e", "-o", "pipefail", "-c", export_script],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert export.returncode == 0, (export.stdout, export.stderr)
    assert metadata.read_bytes() == original_metadata
    summary = json.loads((tmp_path / "mutants" / "mutmut-cicd-stats.json").read_text())
    assert summary["total"] == 2
    assert summary["killed"] == 1
    gate = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "mutation_gate.py"), "0.75"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert gate.returncode == 2, (gate.stdout, gate.stderr)
    assert "PASS" not in gate.stdout
    assert (tmp_path / "mutation-diagnostics" / "export.log").is_file()


def test_workflow_reserves_collection_time_without_weakening_gate():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "    timeout-minutes: 45\n" in workflow
    run_step = _step("Run mutation testing")
    assert "timeout-minutes: 40" in run_step
    assert "python scripts/run_mutation.py" in run_step
    assert "mutmut export-cicd-stats" not in run_step
    assert "ATTUNE_MUTATION_TMP_ROOT" in run_step
    assert "if: always()" in _step("Export mutation evidence")
    gate_step = _step("Gate on mutation score")
    assert "if: always()" in gate_step
    assert "python scripts/mutation_gate.py 0.75" in gate_step
    upload = _step("Retain mutation evidence")
    assert "if: always()" in upload
    for artifact in (
        "mutants/**/*.meta",
        "mutants/mutmut-stats.json",
        "mutants/mutmut-cicd-stats.json",
        "mutation-diagnostics/",
    ):
        assert artifact in upload
    assert "continue-on-error" not in workflow
