"""Bounded, cached child-process observations within one verification scope.

These limits bound resolver work, not trusted executable behavior: child
interpreters and allowlisted commands are still not security sandboxes.
"""

from __future__ import annotations

import math
import os
import signal
import subprocess
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Iterator


class ProbeError(RuntimeError):
    """A provider failed or could not be observed within the declared limits."""


@dataclass
class ProbeBudget:
    """Configurable aggregate child limits; counters include failed attempts."""

    max_attempts: int = 64
    timeout_seconds: float = 30.0
    max_output_bytes: int = 1024 * 1024
    attempts: int = field(default=0, init=False)
    output_bytes: int = field(default=0, init=False)
    _deadline: float | None = field(default=None, init=False, repr=False)
    _cache: dict[tuple[str, ...], subprocess.CompletedProcess[str] | ProbeError] = field(
        default_factory=dict, init=False, repr=False
    )

    def __post_init__(self) -> None:
        for name in ("max_attempts", "max_output_bytes"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if (
            type(self.timeout_seconds) not in (int, float)
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be finite and positive")


_ACTIVE: ContextVar[ProbeBudget | None] = ContextVar("attune_probe_budget", default=None)


@contextmanager
def probe_scope(budget: ProbeBudget | None = None) -> Iterator[ProbeBudget]:
    """Open a scope, or reuse the enclosing verification's budget and cache."""
    active = _ACTIVE.get()
    if active is not None:
        yield active
        return
    budget = budget if budget is not None else ProbeBudget()
    if budget._deadline is None:
        budget._deadline = time.monotonic() + budget.timeout_seconds
    token = _ACTIVE.set(budget)
    try:
        yield budget
    finally:
        _ACTIVE.reset(token)


def run_probe(argv: list[str], *, timeout: float = 10.0) -> subprocess.CompletedProcess[str]:
    """Capture UTF-8 output with aggregate attempt, deadline and byte limits.

    Identical argv reuses its observation, including failure, only within the
    active scope. Callers still record each claim and its document location.
    """
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    with probe_scope() as budget:
        key = tuple(argv)
        cached = budget._cache.get(key)
        if isinstance(cached, ProbeError):
            raise ProbeError(str(cached))
        if cached is not None:
            return cached
        try:
            result = _capture(argv, timeout, budget)
        except (OSError, ValueError, ProbeError) as exc:
            failure = ProbeError(str(exc))
            budget._cache[key] = failure
            raise failure from exc
        budget._cache[key] = result
        return result


def _terminate(process: subprocess.Popen) -> None:
    """Stop the child; on POSIX also stop descendants holding captured pipes."""
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
            return
        except ProcessLookupError:
            return
        except OSError:
            pass
    if process.poll() is None:
        process.kill()


def _capture(
    argv: list[str], timeout: float, budget: ProbeBudget
) -> subprocess.CompletedProcess[str]:
    now = time.monotonic()
    assert budget._deadline is not None
    if now >= budget._deadline:
        raise ProbeError("Probe deadline exhausted")
    if budget.attempts >= budget.max_attempts:
        raise ProbeError(f"Probe attempt limit exhausted ({budget.max_attempts})")
    available = budget.max_output_bytes - budget.output_bytes
    if available <= 0:
        raise ProbeError(f"Probe output limit exhausted ({budget.max_output_bytes} bytes)")
    budget.attempts += 1
    deadline = min(budget._deadline, now + timeout)
    process = subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=os.name == "posix",
    )
    buffers = [bytearray(), bytearray()]
    lock = threading.Lock()
    changed = threading.Event()
    overflow = threading.Event()
    stopped = threading.Event()
    reader_errors: list[OSError] = []

    def read_stream(stream, target: bytearray) -> None:
        try:
            while chunk := stream.read1(65536):
                with lock:
                    if stopped.is_set():
                        return
                    remaining = available - sum(map(len, buffers))
                    target.extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        overflow.set()
                        changed.set()
                        return
        except OSError as exc:
            reader_errors.append(exc)
        finally:
            changed.set()

    readers = [
        threading.Thread(target=read_stream, args=(stream, target), daemon=True)
        for stream, target in zip((process.stdout, process.stderr), buffers, strict=True)
    ]
    started = []
    try:
        for reader in readers:
            reader.start()
            started.append(reader)
        while True:
            if overflow.is_set():
                raise ProbeError(f"Probe output limit exhausted ({budget.max_output_bytes} bytes)")
            if reader_errors:
                raise ProbeError(f"Probe output read failed: {reader_errors[0]}")
            if process.poll() is not None and not any(reader.is_alive() for reader in readers):
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProbeError("Probe timeout or deadline exhausted")
            changed.wait(min(remaining, 0.02))
            changed.clear()
        return subprocess.CompletedProcess(
            argv, process.returncode, buffers[0].decode("utf-8"), buffers[1].decode("utf-8")
        )
    finally:
        with lock:
            stopped.set()
        if process.poll() is None or any(reader.is_alive() for reader in readers):
            _terminate(process)
        process.wait()
        for reader in started:
            reader.join(timeout=0.2)
        for reader, stream in zip(readers, (process.stdout, process.stderr), strict=True):
            # A foreign descendant can inherit a pipe on Windows. Do not let
            # closing a buffer held by its reader defeat the caller deadline.
            if not reader.is_alive():
                stream.close()
        budget.output_bytes += sum(map(len, buffers))
