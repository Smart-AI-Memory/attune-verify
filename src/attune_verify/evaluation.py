"""Evaluate document-level rejection labels without inventing human validation."""

from __future__ import annotations

import time

from attune_verify import VerifyContext, verify


def evaluate(corpus: dict, context: VerifyContext) -> dict:
    """Measure error detection and abstention on explicitly labeled documents.

    Precision/recall concern document-level error detection, not claim extraction
    completeness. Human held-out metrics require reviewer-attributed labels.
    """
    if (
        not isinstance(corpus, dict)
        or corpus.get("schema_version") != 1
        or not isinstance(corpus.get("cases"), list)
    ):
        raise ValueError("Invalid evaluation corpus")
    rows = []
    for case in corpus["cases"]:
        if not isinstance(case, dict) or not isinstance(case.get("content"), str):
            raise ValueError("Each case requires content")
        identifier = case.get("id")
        if identifier is not None and not isinstance(identifier, str):
            raise ValueError("Case id must be a string or null")
        expected = case.get("expected_error")
        if expected is not None and type(expected) is not bool:
            raise ValueError("expected_error must be boolean or null")
        human = case.get("label_basis") == "human" and case.get("split") == "heldout"
        if human and (not case.get("reviewer") or expected is None):
            raise ValueError("Human held-out labels require a reviewer and expected_error")
        started = time.perf_counter()
        result = verify(case["content"], context)
        rows.append(
            {
                "id": identifier,
                "expected_error": expected,
                "predicted_error": not result.ok,
                "status": result.status,
                "unknown_claims": result.coverage["unknown"],
                "supported_claims": result.coverage["total"],
                "elapsed_seconds": time.perf_counter() - started,
                "human_heldout": bool(human),
            }
        )
    labeled = [row for row in rows if row["expected_error"] is not None]
    human_rows = [row for row in labeled if row["human_heldout"]]
    return {
        "schema_version": 1,
        "unit": "document error detection",
        "cases": rows,
        "metrics": _metrics(labeled),
        "human_validated_metrics": _metrics(human_rows) if human_rows else None,
        "unlabeled_cases": len(rows) - len(labeled),
        "elapsed_seconds": sum(row["elapsed_seconds"] for row in rows),
    }


def _metrics(rows: list[dict]) -> dict:
    tp = sum(row["predicted_error"] and row["expected_error"] for row in rows)
    fp = sum(row["predicted_error"] and not row["expected_error"] for row in rows)
    fn = sum(not row["predicted_error"] and row["expected_error"] for row in rows)
    return {
        "documents": len(rows),
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "abstention_rate": (
            sum(row["status"] == "unknown" for row in rows) / len(rows) if rows else None
        ),
        "unknown_claims": sum(row["unknown_claims"] for row in rows),
    }
