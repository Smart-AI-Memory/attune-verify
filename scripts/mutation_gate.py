#!/usr/bin/env python3
"""Gate CI on the mutation score produced by ``mutmut export-cicd-stats``.

``mutmut run`` exits 0 even when mutants survive, so it cannot gate on its own.
This reads ``mutants/mutmut-cicd-stats.json`` and fails when the kill rate falls
below the threshold.

Usage:
    python scripts/mutation_gate.py [threshold]   # threshold default 0.75
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

STATS = Path("mutants/mutmut-cicd-stats.json")
COUNTS = {
    "killed",
    "survived",
    "no_tests",
    "skipped",
    "suspicious",
    "timeout",
    "check_was_interrupted_by_user",
    "segfault",
}


def main() -> int:
    try:
        threshold = float(sys.argv[1]) if len(sys.argv) > 1 else 0.75
        if not math.isfinite(threshold) or not 0 < threshold <= 1:
            raise ValueError("threshold must be finite and in (0, 1]")
        stats = json.loads(STATS.read_text(encoding="utf-8"))
        if not isinstance(stats, dict) or not {"killed", "survived"} <= stats.keys():
            raise ValueError("mutation evidence must include killed and survived counts")
        if stats.keys() - (COUNTS | {"total"}):
            raise ValueError("unsupported mutation statistics schema")
        if any(type(value) is not int or value < 0 for value in stats.values()):
            raise ValueError("mutation counts must be nonnegative integers")
        total = sum(stats.get(key, 0) for key in COUNTS)
        if stats.get("total", total) != total:
            raise ValueError("mutation total includes unaccounted or untested outcomes")
        if not total or not stats["killed"] + stats["survived"]:
            raise ValueError("no completed mutation tests; evidence is inconclusive")
        if any(
            stats.get(key, 0) for key in ("suspicious", "check_was_interrupted_by_user", "segfault")
        ):
            raise ValueError("mutation run has unresolved execution failures")
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        print(f"ERROR: invalid or incomplete mutation evidence: {exc}")
        return 2
    killed = stats["killed"]
    survived = stats["survived"]
    # Missing tests, skips and timeouts are not successful kills. Keeping them
    # in the denominator prevents partial evidence inflating the result.
    score = killed / total

    print(
        f"mutation score: {killed}/{total} killed = {score:.1%} "
        f"(threshold {threshold:.0%}); survived={survived}, "
        f"no_tests={stats.get('no_tests', 0)}, timeout={stats.get('timeout', 0)}, "
        f"skipped={stats.get('skipped', 0)}"
    )
    if score < threshold:
        print(f"FAIL: mutation score {score:.1%} below threshold {threshold:.0%}")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
