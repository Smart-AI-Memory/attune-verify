"""Run all mutation tests with periodic worker diagnostics.

The workflow reserves time after this command for exporting partial results and
uploading evidence. This wrapper preserves mutmut's exit status; interruption is
always a failure, even if mutmut handles its termination signal successfully.
An opt-in Linux RSS guard sends SIGXCPU to oversized mutant workers, which mutmut
classifies as a timeout, never a kill. Forced termination fails this wrapper.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

COMMAND = ["mutmut", "run", "--max-children", "4"]


def _positive_interval(value: str) -> float:
    interval = float(value)
    if not math.isfinite(interval) or interval <= 0:
        raise argparse.ArgumentTypeError("interval must be finite and positive")
    return interval


def _positive_mib(value: str) -> int:
    try:
        limit = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("RSS limit must be a positive integer in MiB") from exc
    if limit <= 0:
        raise argparse.ArgumentTypeError("RSS limit must be a positive integer in MiB")
    return limit


def _linux_process(pid: int) -> dict | None:
    try:
        # comm can contain spaces and parentheses; the last ')' ends field 2.
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    except (FileNotFoundError, ProcessLookupError):
        return None
    return {
        "state": fields[0],
        "ppid": int(fields[1]),
        "start_time_ticks": int(fields[19]),
        "rss_bytes": int(fields[21]) * os.sysconf("SC_PAGE_SIZE"),
    }


def _linux_children(pid: int) -> set[int]:
    children = set()
    try:
        tasks = list(Path(f"/proc/{pid}/task").iterdir())
    except (FileNotFoundError, ProcessLookupError):
        return children
    for task in tasks:
        try:
            children.update(int(child) for child in (task / "children").read_text().split())
        except (FileNotFoundError, ProcessLookupError):
            if task.is_dir():
                raise OSError(f"Linux child-process list is unavailable for {task}") from None
            continue
    return children


def _linux_title(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0", 1)[0].decode(errors="replace")
    except (FileNotFoundError, ProcessLookupError):
        return ""


class _LinuxRssGuard:
    def __init__(self, parent_pid: int, limit_mib: int, directory: Path):
        self.parent_pid = parent_pid
        self.threshold = limit_mib * 1024 * 1024
        self.pending = {}
        self.seen = set()
        self.baseline_peak = 0
        self.worker_peak = 0
        self.forced_termination = False
        self.output = (directory / "rss-events.jsonl").open("w", encoding="utf-8")

    def _event(self, **fields):
        event = {"timestamp": datetime.now(timezone.utc).isoformat(), **fields}
        line = json.dumps(event, sort_keys=True)
        self.output.write(line + "\n")
        self.output.flush()
        print(f"\nMutation RSS guard: {line}", flush=True)

    def _owned_mutant(self, pid: int, state: dict) -> str:
        if state["ppid"] != self.parent_pid or state["state"] == "Z":
            return ""
        title = _linux_title(pid)
        # Baseline/forced-fail checks run in the parent. Their helper processes
        # must not receive mutation timeout signals.
        return title if re.fullmatch(r"mutmut: \S+__mutmut_[0-9]+", title) else ""

    def poll(self):
        now = time.monotonic()
        if not self.seen:
            parent = _linux_process(self.parent_pid)
            if parent:
                self.baseline_peak = max(self.baseline_peak, parent["rss_bytes"])
        for pid in _linux_children(self.parent_pid):
            state = _linux_process(pid)
            title = self._owned_mutant(pid, state) if state else ""
            if not title:
                continue
            if not self.seen:
                self._event(
                    event="baseline_observed",
                    parent_pid=self.parent_pid,
                    baseline_parent_peak_rss_bytes=self.baseline_peak,
                    first_worker_rss_bytes=state["rss_bytes"],
                    threshold_bytes=self.threshold,
                )
            self.seen.add((pid, state["start_time_ticks"]))
            self.worker_peak = max(self.worker_peak, state["rss_bytes"])
            if state["rss_bytes"] <= self.threshold or pid in self.pending:
                continue
            try:
                descriptor = os.pidfd_open(pid)
            except ProcessLookupError:
                continue
            try:
                current = _linux_process(pid)
                if (
                    not current
                    or current["start_time_ticks"] != state["start_time_ticks"]
                    or current["rss_bytes"] <= self.threshold
                    or self._owned_mutant(pid, current) != title
                ):
                    continue
                signal.pidfd_send_signal(descriptor, signal.SIGXCPU)
                event = {
                    "pid": pid,
                    "ppid": current["ppid"],
                    "start_time_ticks": current["start_time_ticks"],
                    "rss_bytes": current["rss_bytes"],
                    "threshold_bytes": self.threshold,
                    "command": title,
                }
                self.pending[pid] = (descriptor, now, event)
                descriptor = None  # The pending record owns the descriptor now.
                self._event(**event, signal="SIGXCPU", classification="timeout")
            except ProcessLookupError:
                pass
            finally:
                if descriptor is not None:
                    os.close(descriptor)

        for pid, (descriptor, sent_at, event) in list(self.pending.items()):
            state = _linux_process(pid)
            if (
                not state
                or state["state"] == "Z"
                or state["ppid"] != self.parent_pid
                or state["start_time_ticks"] != event["start_time_ticks"]
            ):
                os.close(descriptor)
                del self.pending[pid]
            elif now - sent_at >= 1:
                try:
                    signal.pidfd_send_signal(descriptor, signal.SIGKILL)
                    self.forced_termination = True
                    self._event(
                        **{**event, "rss_bytes": state["rss_bytes"]},
                        signal="SIGKILL",
                        elapsed_since_sigxcpu_seconds=round(now - sent_at, 3),
                        classification="wrapper_failure",
                    )
                except ProcessLookupError:
                    pass
                os.close(descriptor)
                del self.pending[pid]

    def summary(self):
        return {
            "parent_pid": self.parent_pid,
            "threshold_bytes": self.threshold,
            "baseline_parent_peak_rss_bytes": self.baseline_peak,
            "worker_peak_rss_bytes": self.worker_peak,
            "observed_workers": len(self.seen),
            "forced_termination": self.forced_termination,
        }

    def close(self):
        for descriptor, _, _ in self.pending.values():
            os.close(descriptor)
        self.pending.clear()
        self.output.close()


def _snapshot(pid: int, started: float) -> dict:
    snapshot = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_elapsed_seconds": round(time.monotonic() - started, 3),
        "parent_pid": pid,
        "processes": [],
    }
    try:
        result = subprocess.run(
            ["ps", "-axww", "-o", "pid=,ppid=,etime=,pcpu=,rss=,stat=,args="],
            capture_output=True,
            text=True,
            timeout=1,
            check=True,
            env={**os.environ, "LC_ALL": "C"},
        )
        for line in result.stdout.splitlines():
            fields = line.split(None, 6)
            if len(fields) != 7:
                continue
            child_pid, parent_pid, elapsed, cpu, rss, state, command = fields
            if int(child_pid) == pid or int(parent_pid) == pid:
                snapshot["processes"].append(
                    {
                        "pid": int(child_pid),
                        "ppid": int(parent_pid),
                        "elapsed": elapsed,
                        "cpu_percent": float(cpu),
                        "rss_kib": int(rss),
                        "state": state,
                        "command": command,
                    }
                )
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        # Missing process diagnostics must not replace the mutation exit status.
        snapshot["diagnostic_error"] = str(exc)
    return snapshot


def _terminate_group(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=3)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        pass
    finally:
        # Also remove surviving children after the parent has exited.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            # A kernel-blocked child must not prevent retaining run status.
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=_positive_interval, default=30.0)
    parser.add_argument("--diagnostics-dir", type=Path, default=Path("mutation-diagnostics"))
    parser.add_argument("--max-worker-rss-mib", type=_positive_mib)
    args = parser.parse_args(argv)
    core_settings = {}
    if args.max_worker_rss_mib is not None:
        if (
            sys.platform != "linux"
            or not hasattr(os, "pidfd_open")
            or not hasattr(signal, "pidfd_send_signal")
            or not Path("/proc/self/stat").is_file()
        ):
            parser.error("the RSS guard requires Linux procfs and pidfd signal support")
        try:
            Path(f"/proc/self/task/{os.getpid()}/children").read_text()
            descriptor = os.pidfd_open(os.getpid())
            try:
                signal.pidfd_send_signal(descriptor, 0)
            finally:
                os.close(descriptor)
            # Suppress ordinary core files only for this process and descendants.
            # Host core_pattern pipe handlers may ignore RLIMIT_CORE.
            import resource

            _, hard_limit = resource.getrlimit(resource.RLIMIT_CORE)
            resource.setrlimit(resource.RLIMIT_CORE, (0, hard_limit))
            core_settings["rlimit_core"] = list(resource.getrlimit(resource.RLIMIT_CORE))
        except (OSError, ValueError) as exc:
            parser.error(
                f"the Linux RSS guard requires child-process lists and working pidfds: {exc}"
            )
        try:
            core_settings["core_pattern"] = (
                Path("/proc/sys/kernel/core_pattern").read_text().rstrip("\n")
            )
        except OSError as exc:
            core_settings["core_pattern_error"] = str(exc)
    args.diagnostics_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    interrupted_signal = None

    def interrupted(signum, _frame):
        nonlocal interrupted_signal
        if interrupted_signal is None:
            interrupted_signal = signum

    previous_handlers = {
        signum: signal.signal(signum, interrupted) for signum in (signal.SIGINT, signal.SIGTERM)
    }
    exit_code = 1
    process = None
    guard = None
    status = {"command": COMMAND, **core_settings}
    try:
        with (args.diagnostics_dir / "workers.jsonl").open("w", encoding="utf-8") as output:
            process = subprocess.Popen(COMMAND, start_new_session=True)
            if args.max_worker_rss_mib is not None:
                guard = _LinuxRssGuard(process.pid, args.max_worker_rss_mib, args.diagnostics_dir)

            def record():
                snapshot = _snapshot(process.pid, started)
                line = json.dumps(snapshot, sort_keys=True)
                output.write(line + "\n")
                output.flush()
                print(f"\nMutation workers: {line}", flush=True)

            next_snapshot = 0.0
            while process.poll() is None and interrupted_signal is None:
                if guard is not None:
                    guard.poll()
                    if guard.forced_termination:
                        break
                now = time.monotonic()
                if now >= next_snapshot:
                    record()
                    next_snapshot = now + args.interval
                time.sleep(min(0.1, args.interval))
            record()
            if interrupted_signal is not None:
                _terminate_group(process)
                exit_code = 128 + interrupted_signal
            elif guard is not None and guard.forced_termination:
                # SIGKILL is not a mutation kill. Preserve partial evidence and
                # fail the run without rewriting any of mutmut's verdicts.
                _terminate_group(process)
                exit_code = 1
            else:
                exit_code = process.returncode
                if exit_code < 0:
                    exit_code = 128 - exit_code
    except OSError as exc:
        status["error"] = str(exc)
        if process is not None:
            _terminate_group(process)
    finally:
        if guard is not None:
            status["rss_guard"] = guard.summary()
            guard.close()
        status.update(
            exit_code=exit_code,
            interrupted_signal=interrupted_signal,
            elapsed_seconds=round(time.monotonic() - started, 3),
        )
        (args.diagnostics_dir / "run-status.json").write_text(
            json.dumps(status, indent=2) + "\n", encoding="utf-8"
        )
        for signum, previous in previous_handlers.items():
            signal.signal(signum, previous)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
