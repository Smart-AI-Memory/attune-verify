"""Corpus harness: run verify() over labeled cases, gate on precision/recall.

Two tests:
- ``test_case`` (parametrized): per-case assertion that predicted error findings
  match the ground truth exactly — pinpoints which case regressed.
- ``test_precision_recall_gate``: aggregate precision/recall over all cases'
  error-severity findings, gated at the thresholds below. This is the trust
  signal — a checker that silently passes hallucinations drops recall; one that
  flags real entities drops precision.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from attune_verify import VerifyContext, verify
from attune_verify.result import Finding

from .cases import CASES, CorpusCase, ExpectedFinding

PRECISION_THRESHOLD = 0.95
RECALL_THRESHOLD = 0.95


def _build_context(case: CorpusCase, tmp_path: Path) -> VerifyContext:
    """Materialize the case's declared files and assemble its context."""
    for rel in case.files:
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("placeholder\n", encoding="utf-8")
    return VerifyContext(
        project_root=tmp_path,
        env_python=sys.executable,
        help_commands=dict(case.help_commands),
        count_sources=dict(case.count_sources),
    )


def _errors(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if f.severity == "error"]


def _matches(expected: ExpectedFinding, finding: Finding) -> bool:
    haystack = f"{finding.detail} {finding.evidence}"
    return finding.kind == expected.kind and expected.contains in haystack


def _score(expected: tuple[ExpectedFinding, ...], predicted: list[Finding]) -> tuple[int, int, int]:
    """Return (true_positives, false_positives, false_negatives) for one case.

    Greedy one-to-one matching: each predicted finding consumes at most one
    expected finding and vice versa.
    """
    remaining = list(predicted)
    tp = 0
    for exp in expected:
        hit = next((f for f in remaining if _matches(exp, f)), None)
        if hit is not None:
            remaining.remove(hit)
            tp += 1
    false_neg = len(expected) - tp
    false_pos = len(remaining)
    return tp, false_pos, false_neg


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_case(case: CorpusCase, tmp_path: Path) -> None:
    ctx = _build_context(case, tmp_path)
    predicted = _errors(verify(case.content, ctx).findings)
    tp, false_pos, false_neg = _score(case.expected, predicted)
    assert false_neg == 0, (
        f"{case.name}: missed {false_neg} expected finding(s). "
        f"predicted={[(f.kind.value, f.detail) for f in predicted]}"
    )
    assert false_pos == 0, (
        f"{case.name}: {false_pos} false positive(s). "
        f"predicted={[(f.kind.value, f.detail) for f in predicted]}"
    )
    assert tp == len(case.expected)


def test_precision_recall_gate(tmp_path_factory: pytest.TempPathFactory) -> None:
    total_tp = total_fp = total_fn = 0
    for case in CASES:
        ctx = _build_context(case, tmp_path_factory.mktemp(case.name))
        predicted = _errors(verify(case.content, ctx).findings)
        tp, false_pos, false_neg = _score(case.expected, predicted)
        total_tp += tp
        total_fp += false_pos
        total_fn += false_neg

    precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) else 1.0
    recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) else 1.0
    assert precision >= PRECISION_THRESHOLD, (
        f"precision {precision:.3f} < {PRECISION_THRESHOLD} "
        f"(tp={total_tp} fp={total_fp} fn={total_fn})"
    )
    assert (
        recall >= RECALL_THRESHOLD
    ), f"recall {recall:.3f} < {RECALL_THRESHOLD} (tp={total_tp} fp={total_fp} fn={total_fn})"
