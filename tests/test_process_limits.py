"""Real bounded child fixtures; no model, network, or installed commands required."""

import math
import os
import sys
import time

import pytest


def process_api():
    from attune_verify._process import ProbeBudget, ProbeError, probe_scope, run_probe

    return ProbeBudget, ProbeError, probe_scope, run_probe


def test_attempt_limit_caches_successes_and_rejects_new_work():
    ProbeBudget, ProbeError, scope, run = process_api()
    budget = ProbeBudget(max_attempts=1)
    argv = [sys.executable, "-c", "import os; os.write(1, b'hello\\n')"]
    with scope(budget):
        assert run(argv).stdout == "hello\n"
        assert run(argv).stdout == "hello\n"
        with pytest.raises(ProbeError, match="attempt"):
            run([sys.executable, "-c", "print('different')"])
    assert budget.attempts == 1


def test_output_limit_bounds_both_streams_and_reports_unknown():
    ProbeBudget, ProbeError, scope, run = process_api()
    budget = ProbeBudget(max_output_bytes=1024)
    with scope(budget), pytest.raises(ProbeError, match="output"):
        run([sys.executable, "-c", "import os; os.write(1,b'x'*768); os.write(2,b'y'*768)"])
    assert budget.output_bytes <= 1024


def test_output_limit_is_cumulative_across_children():
    ProbeBudget, ProbeError, scope, run = process_api()
    budget = ProbeBudget(max_output_bytes=1024)
    with scope(budget):
        run([sys.executable, "-c", "print('x'*700)"])
        with pytest.raises(ProbeError, match="output"):
            run([sys.executable, "-c", "print('y'*700)"])


def test_deadline_applies_to_child_and_nested_scopes():
    ProbeBudget, ProbeError, scope, run = process_api()
    budget = ProbeBudget(timeout_seconds=0.2)
    started = time.monotonic()
    with scope(budget):
        with scope(ProbeBudget(timeout_seconds=30)) as inherited:
            assert inherited is budget
            with pytest.raises(ProbeError, match="timeout|deadline"):
                run([sys.executable, "-c", "import time; time.sleep(5)"])
        with pytest.raises(ProbeError, match="deadline"):
            run([sys.executable, "-c", "print('late')"])
    assert time.monotonic() - started < 2


def test_failures_are_cached_inside_scope():
    ProbeBudget, ProbeError, scope, run = process_api()
    budget = ProbeBudget()
    with scope(budget):
        for _ in range(3):
            with pytest.raises(ProbeError):
                run(["/missing-fixture-python-01"])
    assert budget.attempts == 1


@pytest.mark.parametrize("field", ["max_attempts", "max_output_bytes", "timeout_seconds"])
@pytest.mark.parametrize("value", [0, -1, True, math.inf, math.nan])
def test_invalid_limits_are_rejected(field, value):
    ProbeBudget, _, _, _ = process_api()
    with pytest.raises((TypeError, ValueError)):
        ProbeBudget(**{field: value})


def test_direct_checker_scope_limits_become_per_claim_unknowns():
    from attune_verify._extract import CodeFence
    from attune_verify.checkers.flags import check_flags
    from attune_verify.checkers.imports import check_imports

    ProbeBudget, _, scope, _ = process_api()
    claims = []
    with scope(ProbeBudget(max_attempts=1)):
        check_imports([CodeFence("python", "import os\nimport sys\n")], claims=claims)
        check_flags(f"`{sys.executable} --help`", {}, frozenset({sys.executable}), claims=claims)
    assert [c.status.value for c in claims] == ["verified", "unknown", "unknown"]
    assert all("attempt" in c.detail for c in claims[1:])


def test_completed_evidence_survives_output_budget_exhaustion(tmp_path, monkeypatch):
    from attune_verify import VerifyContext, verify

    ProbeBudget, _, scope, _ = process_api()
    (tmp_path / "loud_fixture_01.py").write_text("import os\nos.write(1, b'x'*8192)\nVALUE = 1\n")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    with scope(ProbeBudget(max_output_bytes=1024)):
        result = verify(
            "```python\nimport missing_fixture_01\n"
            "from loud_fixture_01 import VALUE\nimport os\n```",
            VerifyContext(),
        )
    assert [c.status.value for c in result.claims] == ["refuted", "unknown", "unknown"]
    assert not result.ok
    assert all("output limit" in c.detail for c in result.claims[1:])


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group cleanup")
def test_descendant_pipe_does_not_defeat_deadline():
    ProbeBudget, ProbeError, scope, run = process_api()
    started = time.monotonic()
    # The direct child exits while a descendant keeps its stdout pipe open.
    program = (
        "import subprocess, sys\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(5)'])\n"
    )
    with scope(ProbeBudget(timeout_seconds=0.2)), pytest.raises(ProbeError, match="deadline"):
        run([sys.executable, "-c", program])
    assert time.monotonic() - started < 2


def test_scope_does_not_reuse_observations_in_later_runs(tmp_path):
    ProbeBudget, _, scope, run = process_api()
    source = tmp_path / "value.txt"
    argv = [
        sys.executable,
        "-c",
        "from pathlib import Path; import sys; print(Path(sys.argv[1]).read_text())",
        str(source),
    ]
    source.write_text("before")
    with scope(ProbeBudget()):
        assert run(argv).stdout.strip() == "before"
        source.write_text("after")
        assert run(argv).stdout.strip() == "before"
    with scope(ProbeBudget()):
        assert run(argv).stdout.strip() == "after"
