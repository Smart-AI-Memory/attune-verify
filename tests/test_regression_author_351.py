"""Regression fixture for attune-author PR #351 hallucinations.

PR #351 surfaced six distinct hallucination *shapes* in LLM-generated docs.
This fixture captures all six as one known-bad markdown string and asserts
that the four AST/deterministically-detectable shapes are flagged by verify():

    1. COUNT_MISMATCH    — a claimed count that disagrees with source.
    2. DEAD_LINK         — "See also" links to docs that do not exist.
    3. UNKNOWN_FLAG      — a CLI flag absent from the command's --help.
    4. UNRESOLVED_IMPORT — an import of a private path that does not resolve.

The remaining two shapes are *semantic* — no AST signal exists for them, so
the deterministic checkers cannot and should not catch them:

    5. wrong route path      — "POST /run" where the real route is "POST /jobs".
    6. missing security note  — binding host="0.0.0.0" with no exposure callout.

These two are documented here as semantic-layer territory and exercised via a
stub Judge (test_semantic_only_shapes) rather than forced through the
deterministic checkers.

SELF-CONTAINED: this test must not depend on attune-ai being installed in the
environment. The import checker only validates the *top-level* package, and
attune-ai may or may not be importable in any given venv (it IS in the dev
pyenv, is NOT in a clean CI venv). To make the import-shape assertion
deterministic regardless, we patch _resolves to simulate "not installed" —
the exact condition under which PR #351's hallucinated import broke.
"""

from unittest.mock import patch

from attune_verify import FindingKind, VerifyContext, verify
from attune_verify.semantic.protocol import SemanticVerdict

# --- The known-bad doc: all six PR #351 hallucination shapes in one string ---
KNOWN_BAD_DOC = "\n".join(
    [
        "# Known-bad doc capturing attune-author hallucinations",
        "",
        "attune ships with 498 templates out of the box.",  # shape 1: count
        "",
        "## See also",
        "- [Reader API](docs/reader-api.md)",  # shape 2: dead links (x4)
        "- [Models reference](docs/models.md)",
        "- [Ops guide](guides/ops.md)",
        "- [Template index](reference/templates.md)",
        "",
        "Enable raw execution with `attune` `--allow-run`.",  # shape 3: unknown flag
        "",
        "```python",  # shape 4: bad imports
        "from attune.ops._readers import _read_templates",
        "from attune.ops._models import TemplateModel",
        "```",
        "",
        "Send work to the worker via `POST /run`.",  # shape 5: wrong route (semantic)
        'Bind the server with host="0.0.0.0".',  # shape 6: missing callout (semantic)
    ]
)

# attune --help WITHOUT --allow-run: the flag is a hallucination.
_ATTUNE_HELP = "\n".join(
    [
        "Usage: attune [OPTIONS] COMMAND [ARGS]...",
        "",
        "Options:",
        "  --level TEXT  Set the discovery level.",
        "  --help        Show this message and exit.",
    ]
)


def _deterministic_context(tmp_path):
    """Context that boundary-declares every deterministic truth source."""
    return VerifyContext(
        project_root=tmp_path,  # empty -> links are dead
        help_commands={"attune": _ATTUNE_HELP},  # flag not in help -> error
        count_sources={"templates": 259},  # claim says 498 -> mismatch
    )


def test_deterministic_shapes_flagged(tmp_path):
    """The four AST-detectable PR #351 shapes are all flagged as errors."""
    ctx = _deterministic_context(tmp_path)

    # Simulate "attune not installed" so the import shape is caught
    # deterministically, independent of the ambient environment.
    with patch("attune_verify.checkers.imports._resolves", return_value=False):
        result = verify(KNOWN_BAD_DOC, ctx)

    assert result.ok is False

    error_kinds = {f.kind for f in result.findings if f.severity == "error"}
    assert FindingKind.COUNT_MISMATCH in error_kinds
    assert FindingKind.DEAD_LINK in error_kinds
    assert FindingKind.UNKNOWN_FLAG in error_kinds
    assert FindingKind.UNRESOLVED_IMPORT in error_kinds

    # All four "See also" links point at nonexistent docs.
    dead = [f for f in result.findings if f.kind is FindingKind.DEAD_LINK and f.severity == "error"]
    assert len(dead) == 4


def test_count_mismatch_detail_names_the_source(tmp_path):
    """The mismatch finding pins the wrong number to the declared source."""
    ctx = _deterministic_context(tmp_path)
    with patch("attune_verify.checkers.imports._resolves", return_value=False):
        result = verify(KNOWN_BAD_DOC, ctx)

    mismatches = [f for f in result.findings if f.kind is FindingKind.COUNT_MISMATCH]
    assert len(mismatches) == 1
    assert "498" in mismatches[0].detail
    assert "259" in mismatches[0].detail


class _StubJudge:
    """Minimal Judge satisfying the runtime-checkable Judge protocol.

    Flags the two semantic-only PR #351 shapes that no AST signal can catch.
    """

    def score(self, query, answer, passages):
        issues = []
        if "POST /run" in answer:
            issues.append("Route 'POST /run' is wrong; the real route is 'POST /jobs'.")
        if 'host="0.0.0.0"' in answer:
            issues.append('Binding host="0.0.0.0" exposes the server; missing security callout.')
        return SemanticVerdict(faithful=not issues, issues=issues)


def test_semantic_only_shapes_are_semantic_layer_territory():
    """The two non-AST shapes are caught only when a Judge is supplied.

    Deterministic checkers produce no signal for a wrong route path or a
    missing security callout — this documents them as semantic-layer territory.
    """
    # Without a judge, the deterministic checkers see nothing wrong here.
    ctx_no_judge = VerifyContext()
    semantic_only = "\n".join(
        [
            "Send work to the worker via POST /run.",
            'Bind the server with host="0.0.0.0".',
        ]
    )
    assert verify(semantic_only, ctx_no_judge).ok is True

    # With a judge, both shapes surface as SEMANTIC errors.
    ctx = VerifyContext(judge=_StubJudge(), semantic=True)
    result = verify(semantic_only, ctx)
    assert result.semantic_ran is True
    assert result.ok is False
    semantic_findings = [f for f in result.findings if f.kind is FindingKind.SEMANTIC]
    assert len(semantic_findings) == 2
