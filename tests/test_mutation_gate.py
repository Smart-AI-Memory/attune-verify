"""The quality gate must not report absent/invalid evidence as success."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "mutation_gate.py"


@pytest.mark.parametrize(
    "stats",
    [
        {"killed": 0, "survived": 0},
        {"killed": -1, "survived": 0},
        {"killed": True, "survived": 0},
        {"killed": 10, "survived": 0, "suspicious": 1},
    ],
)
def test_inconclusive_or_invalid_mutation_evidence_fails(tmp_path, stats):
    folder = tmp_path / "mutants"
    folder.mkdir()
    (folder / "mutmut-cicd-stats.json").write_text(json.dumps(stats), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "0.75"], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode != 0
    assert "PASS" not in result.stdout


@pytest.mark.parametrize("threshold", ["NaN", "-1", "1.1"])
def test_invalid_threshold_cannot_disable_gate(tmp_path, threshold):
    folder = tmp_path / "mutants"
    folder.mkdir()
    (folder / "mutmut-cicd-stats.json").write_text(
        '{"killed": 1, "survived": 99}', encoding="utf-8"
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), threshold], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == 2


@pytest.mark.parametrize("killed,survived,exit_code", [(3, 1, 0), (2, 2, 1)])
def test_mutation_threshold_is_measured(tmp_path, killed, survived, exit_code):
    folder = tmp_path / "mutants"
    folder.mkdir()
    (folder / "mutmut-cicd-stats.json").write_text(
        json.dumps({"killed": killed, "survived": survived}), encoding="utf-8"
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "0.75"], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == exit_code
