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
import sys
from pathlib import Path

STATS = Path("mutants/mutmut-cicd-stats.json")


def main() -> int:
    threshold = float(sys.argv[1]) if len(sys.argv) > 1 else 0.75
    if not STATS.exists():
        print(f"ERROR: {STATS} not found — run `mutmut run && mutmut export-cicd-stats` first")
        return 2

    stats = json.loads(STATS.read_text())
    killed = stats["killed"]
    survived = stats["survived"]
    tested = killed + survived
    score = killed / tested if tested else 1.0

    print(
        f"mutation score: {killed}/{tested} killed = {score:.1%} "
        f"(threshold {threshold:.0%}); survived={survived}"
    )
    if score < threshold:
        print(f"FAIL: mutation score {score:.1%} below threshold {threshold:.0%}")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
