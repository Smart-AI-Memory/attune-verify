"""Core verify() orchestration — runs all checkers and the semantic layer."""

from __future__ import annotations

import logging
from typing import List

from attune_verify._extract import (
    extract_code_fences,
    extract_links,
    extract_numeric_claims,
)
from attune_verify.checkers.counts import check_counts
from attune_verify.checkers.flags import check_flags
from attune_verify.checkers.imports import check_imports
from attune_verify.checkers.links import check_links
from attune_verify.claims import Claim, Observations, record
from attune_verify.context import VerifyContext
from attune_verify.result import Finding, FindingKind, VerifyResult

logger = logging.getLogger(__name__)


def verify(content: str, context: VerifyContext) -> VerifyResult:
    """Run deterministic checkers and optional semantic layer.

    Deterministic checkers always run and are independent — a failure in
    one does not abort the others. The semantic layer runs only when
    context.semantic is True and both a judge and source passages are
    available.

    Args:
        content: LLM-generated content to verify.
        context: Declared truth boundaries (project root, env, commands,
            count sources, optional judge).

    Returns:
        VerifyResult with all findings. Never raises on findings — use
        raise_if_failed(result) for a hard gate.
    """
    result = VerifyResult()

    # --- Deterministic checkers ---
    _run_checker(result, "imports", _check_imports, content, context)
    _run_checker(result, "flags", _check_flags, content, context)
    _run_checker(result, "links", _check_links, content, context)
    _run_checker(result, "counts", _check_counts, content, context)

    # --- Semantic layer (opt-in) ---
    if context.semantic:
        _run_semantic(result, content, context)

    return result


# ---------------------------------------------------------------------------
# Per-checker wrappers — each catches exceptions and surfaces as a warning
# ---------------------------------------------------------------------------


def _check_imports(content: str, context: VerifyContext) -> List[Finding]:
    fences = extract_code_fences(content)
    claims: list[Claim] = []
    findings = check_imports(fences, env_python=context.env_python, claims=claims)
    return Observations(findings, claims)


def _check_flags(content: str, context: VerifyContext) -> List[Finding]:
    claims: list[Claim] = []
    findings = check_flags(
        content,
        help_commands=context.help_commands,
        allowed_help_cmds=context.allowed_help_cmds,
        claims=claims,
    )
    return Observations(findings, claims)


def _check_links(content: str, context: VerifyContext) -> List[Finding]:
    links = extract_links(content)
    claims: list[Claim] = []
    findings = check_links(
        links, project_root=context.project_root, claims=claims, document_path=context.document_path
    )
    return Observations(findings, claims)


def _check_counts(content: str, context: VerifyContext) -> List[Finding]:
    numeric = extract_numeric_claims(content)
    claims: list[Claim] = []
    findings = check_counts(numeric, count_sources=context.count_sources, observations=claims)
    return Observations(findings, claims)


def _run_checker(
    result: VerifyResult,
    name: str,
    fn: object,
    content: str,
    context: VerifyContext,
) -> None:
    """Run one checker, surfacing any internal exception as a warning."""
    try:
        findings = fn(content, context)  # type: ignore[operator]
        result.findings.extend(findings)
        result.claims.extend(getattr(findings, "claims", []))
        result.checked.append(name)
    except Exception as exc:  # noqa: BLE001
        # INTENTIONAL: individual checker failures must not abort the run.
        logger.exception("checker '%s' raised: %s", name, exc)
        result.findings.append(
            Finding(
                kind=FindingKind.CHECKER_ERROR,
                detail=f"Checker '{name}' failed: {exc}",
                evidence="",
                severity="warning",
            )
        )


def _run_semantic(result: VerifyResult, content: str, context: VerifyContext) -> None:
    """Run the semantic layer if a judge is available."""
    from attune_verify.semantic.protocol import Judge  # noqa: PLC0415

    if context.judge is None:
        detail = (
            "Semantic layer requested (context.semantic=True) "
            "but no judge was provided in VerifyContext.judge"
        )
    elif not isinstance(context.judge, Judge):
        detail = (
            "Semantic layer requested (context.semantic=True) but the "
            f"provided judge ({type(context.judge).__name__}) does not "
            "satisfy the Judge protocol (missing a compatible score())"
        )
    elif not context.passages:
        # Without independent source passages the judge would score the
        # content against itself — vacuously faithful, so skip instead.
        detail = (
            "Semantic layer requested (context.semantic=True) but no "
            "source passages were provided in VerifyContext.passages"
        )
    else:
        detail = None
    if detail is not None:
        result.findings.append(
            Finding(
                kind=FindingKind.SEMANTIC,
                detail=detail,
                evidence="",
                severity="warning",
            )
        )
        record(result.claims, "semantic", "document faithfulness", content, unknown=detail)
        return

    try:
        verdict = context.judge.score(
            query="Verify this generated content for faithfulness",
            answer=content,
            passages=context.passages,
        )
        result.semantic_ran = True
        if not isinstance(verdict.issues, list) or not all(
            isinstance(i, str) for i in verdict.issues
        ):
            raise ValueError("Semantic verdict issues must be a list of strings")
        if type(verdict.faithful) is not bool:
            raise ValueError("Semantic verdict faithful must be a boolean")
        if verdict.faithful and verdict.issues:
            raise ValueError("Faithful verdict contradicts its issues")
        if verdict.faithful:
            record(result.claims, "semantic", "document faithfulness", content)
        if not verdict.faithful:
            for issue in verdict.issues or [
                "Semantic judge rejected the content without an explanation"
            ]:
                result.findings.append(
                    Finding(
                        kind=FindingKind.SEMANTIC,
                        detail=issue,
                        evidence="",
                        severity="error",
                    )
                )
        if not verdict.faithful:
            record(
                result.claims,
                "semantic",
                "document faithfulness",
                content,
                finding=result.findings[-1],
            )
    except Exception as exc:  # noqa: BLE001
        # INTENTIONAL: semantic layer is opt-in; failures degrade gracefully.
        logger.exception("semantic judge raised: %s", exc)
        result.findings.append(
            Finding(
                kind=FindingKind.SEMANTIC,
                detail=f"Semantic judge failed: {exc}",
                evidence="",
                severity="warning",
            )
        )
        record(
            result.claims, "semantic", "document faithfulness", content, finding=result.findings[-1]
        )
