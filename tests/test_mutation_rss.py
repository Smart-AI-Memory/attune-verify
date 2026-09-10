"""The opt-in Linux guard limits owned mutant workers without claiming kills."""

import importlib.util
import json
import os
import shlex
import signal
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_mutation.py"
LINUX_ONLY = pytest.mark.skipif(sys.platform != "linux", reason="requires Linux procfs and pidfds")
WORKER_NAME = "mutmut: example.x_work__mutmut_1"


def _module():
    spec = importlib.util.spec_from_file_location("run_mutation", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rss_fixture(tmp_path, mode):
    """A bounded stand-in for mutmut's fork/wait/metadata behavior."""
    pytest.importorskip("setproctitle")
    executable = tmp_path / "bin" / "mutmut"
    executable.parent.mkdir()
    script = tmp_path / "fake_mutmut.py"
    script.write_text(
        textwrap.dedent(f"""
            import json
            import os
            import resource
            import signal
            import sys
            import time
            from pathlib import Path
            from setproctitle import setproctitle

            assert sys.argv[1:] == ["run", "--max-children", "4"]
            mode = {mode!r}
            metadata = Path("mutants/src/example.py.meta")
            metadata.parent.mkdir(parents=True)
            data = {{"exit_code_by_key": {{"example.x_work__mutmut_1": None}},
                     "durations_by_key": {{}}, "estimated_durations_by_key": {{}}}}
            metadata.write_text(json.dumps(data))
            worker = os.fork()
            if worker == 0:
                Path("worker-resource.json").write_text(
                    json.dumps({{"core_limits": resource.getrlimit(resource.RLIMIT_CORE)}})
                )
                if mode == "ignore":
                    signal.signal(signal.SIGXCPU, signal.SIG_IGN)
                setproctitle({WORKER_NAME!r} if mode != "unrelated" else "baseline-helper")
                # Even a broken guard allocates at most 64 MiB and exits in seconds.
                retained = []
                for _ in range(4 if mode == "healthy" else 64):
                    retained.append(bytearray(1024 * 1024))
                    time.sleep(0.02)
                time.sleep(2)
                os._exit(0)
            _, wait_status = os.waitpid(worker, 0)
            exit_code = os.waitstatus_to_exitcode(wait_status)
            Path("child-exit.json").write_text(
                json.dumps({{"pid": worker, "exit_code": exit_code}})
            )
            data["exit_code_by_key"]["example.x_work__mutmut_1"] = exit_code
            metadata.write_text(json.dumps(data))
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


@LINUX_ONLY
@pytest.mark.parametrize("mode", ["grow", "healthy", "unrelated", "ignore"])
def test_linux_rss_guard_real_children_and_classification(tmp_path, mode):
    import resource

    env = _rss_fixture(tmp_path, mode)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--max-worker-rss-mib", "32"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=12,
    )
    status = json.loads((tmp_path / "mutation-diagnostics" / "run-status.json").read_text())
    events = [
        json.loads(line)
        for line in (tmp_path / "mutation-diagnostics" / "rss-events.jsonl")
        .read_text()
        .splitlines()
    ]
    actions = [event for event in events if "signal" in event]
    if result.returncode != 0:
        # Keep compact evidence visible if pytest truncates the command's stdout.
        print(json.dumps({"status": status, "actions": actions}, indent=2))
    limits = json.loads((tmp_path / "worker-resource.json").read_text())["core_limits"]
    assert limits == [0, resource.getrlimit(resource.RLIMIT_CORE)[1]]
    assert status["rlimit_core"] == limits
    assert status["core_pattern"] == Path("/proc/sys/kernel/core_pattern").read_text().rstrip("\n")
    assert "core_pattern_error" not in status
    assert status["rss_guard"]["threshold_bytes"] == 32 * 1024 * 1024
    assert status["rss_guard"]["baseline_parent_peak_rss_bytes"] > 0
    if mode in ("healthy", "unrelated"):
        assert result.returncode == 0, (result.stdout, result.stderr)
        assert not actions
        assert json.loads((tmp_path / "child-exit.json").read_text())["exit_code"] == 0
        return

    assert actions[0]["signal"] == "SIGXCPU"
    assert actions[0]["rss_bytes"] > actions[0]["threshold_bytes"]
    assert actions[0]["command"] == WORKER_NAME
    assert actions[0]["ppid"] == status["rss_guard"]["parent_pid"]
    assert actions[0]["start_time_ticks"] > 0
    if mode == "ignore":
        assert result.returncode != 0, (result.stdout, result.stderr)
        assert actions[-1]["signal"] == "SIGKILL"
        assert actions[-1]["elapsed_since_sigxcpu_seconds"] >= 1
        assert status["rss_guard"]["forced_termination"] is True
        return

    assert result.returncode == 0, (result.stdout, result.stderr)
    child = json.loads((tmp_path / "child-exit.json").read_text())
    assert child["exit_code"] == -signal.SIGXCPU
    assert child["pid"] == actions[0]["pid"]
    assert len(actions) == 1
    mutmut = pytest.importorskip("mutmut.__main__")
    assert mutmut.status_by_exit_code[child["exit_code"]] == "timeout"
    export = subprocess.run(
        [sys.executable, "-m", "mutmut", "export-cicd-stats"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert export.returncode == 0, (export.stdout, export.stderr)
    summary = json.loads((tmp_path / "mutants" / "mutmut-cicd-stats.json").read_text())
    assert summary["total"] == 1
    assert summary["timeout"] == 1
    assert summary["killed"] == 0
    gate = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "mutation_gate.py"), "0.75"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert gate.returncode == 2
    assert "inconclusive" in gate.stdout
    assert "PASS" not in gate.stdout


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "NaN", "inf"])
def test_invalid_rss_limits_fail_before_launch(tmp_path, value):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--max-worker-rss-mib", value],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 2
    assert "positive integer" in result.stderr
    assert not (tmp_path / "mutation-diagnostics").exists()


def test_rss_limit_fails_clearly_on_unsupported_platform(monkeypatch, capsys, tmp_path):
    module = _module()
    monkeypatch.setattr(module.sys, "platform", "darwin")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as error:
        module.main(["--max-worker-rss-mib", "32"])
    assert error.value.code == 2
    assert "Linux" in capsys.readouterr().err
    assert not (tmp_path / "mutation-diagnostics").exists()


def test_rss_guard_requires_readable_proc_child_lists(monkeypatch, capsys, tmp_path):
    module = _module()
    monkeypatch.setattr(module.sys, "platform", "linux")
    monkeypatch.setattr(module.os, "pidfd_open", lambda pid: 42, raising=False)
    monkeypatch.setattr(module.signal, "pidfd_send_signal", lambda *args: None, raising=False)
    monkeypatch.setattr(module.Path, "is_file", lambda path: True)
    original_read = module.Path.read_text

    def read_text(path, *args, **kwargs):
        if str(path).startswith("/proc/"):
            raise PermissionError("fixture: proc child lists are inaccessible")
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(module.Path, "read_text", read_text)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as error:
        module.main(["--max-worker-rss-mib", "32"])
    assert error.value.code == 2
    assert "child-process lists" in capsys.readouterr().err
    assert not (tmp_path / "mutation-diagnostics").exists()


@pytest.mark.parametrize("change", ["identity", "parent", "title"])
def test_guard_revalidates_process_ownership_before_signaling(tmp_path, monkeypatch, change):
    module = _module()
    observed = {"ppid": 10, "start_time_ticks": 111, "rss_bytes": 64 * 1024 * 1024, "state": "R"}
    second = {**observed}
    if change == "identity":
        second["start_time_ticks"] = 222
    elif change == "parent":
        second["ppid"] = 999
    reads = iter([observed, second])
    monkeypatch.setattr(module, "_linux_children", lambda pid: [20])
    monkeypatch.setattr(
        module, "_linux_process", lambda pid: observed if pid == 10 else next(reads)
    )
    title_reads = iter([WORKER_NAME, "unrelated" if change == "title" else WORKER_NAME])
    monkeypatch.setattr(module, "_linux_title", lambda pid: next(title_reads))
    monkeypatch.setattr(module.os, "pidfd_open", lambda pid: 42, raising=False)
    closed = []
    monkeypatch.setattr(module.os, "close", closed.append)
    signaled = []
    monkeypatch.setattr(
        module.signal, "pidfd_send_signal", lambda *args: signaled.append(args), raising=False
    )
    guard = module._LinuxRssGuard(10, 32, tmp_path)
    try:
        guard.poll()
    finally:
        guard.close()
    assert not signaled
    assert closed == [42]


def test_ci_opts_in_to_one_gib_per_worker():
    workflow = (ROOT / ".github" / "workflows" / "mutation.yml").read_text()
    assert "python scripts/run_mutation.py --max-worker-rss-mib 1024" in workflow
