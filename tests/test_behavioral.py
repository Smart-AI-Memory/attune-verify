"""Behavioral tests for the orchestration, error/warning paths, and extractors.

These target the parts the happy-path corpus does not exercise: the
exception-isolation wrapper, the semantic orchestration, the link/flag warning
and subprocess branches, and the extractor edge cases (line numbers, language
defaulting, context windows). They were written to kill mutation-testing
survivors — each assertion pins a specific behavior, not just "it ran".
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from attune_verify import VerifyContext, verify
from attune_verify import _verify as verify_mod
from attune_verify._extract import (
    CodeFence,
    MarkdownLink,
    NumericClaim,
    extract_code_fences,
    extract_links,
    extract_numeric_claims,
)
from attune_verify.checkers.counts import check_counts
from attune_verify.checkers.flags import _get_help, _guess_command, check_flags
from attune_verify.checkers.imports import check_imports
from attune_verify.checkers.links import check_links
from attune_verify.result import (
    Finding,
    FindingKind,
    VerificationError,
    VerifyResult,
)
from attune_verify.semantic.protocol import SemanticVerdict


# ---------------------------------------------------------------------------
# _run_checker: a checker raising must not abort the run (exception isolation)
# ---------------------------------------------------------------------------
def test_checker_exception_becomes_warning_and_run_continues(monkeypatch):
    def boom(content, context):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(verify_mod, "_check_imports", boom)
    result = verify("no imports here", VerifyContext())

    # The failing checker surfaces a warning, never raises.
    infra = [f for f in result.findings if f.severity == "warning" and "imports" in f.detail]
    assert len(infra) == 1
    assert "kaboom" in infra[0].detail
    assert infra[0].severity == "warning"
    # Infra failures carry their own kind — not a repurposed content kind.
    assert infra[0].kind is FindingKind.CHECKER_ERROR
    # The failed checker is NOT recorded as checked, but the others are.
    assert "imports" not in result.checked
    assert {"flags", "links", "counts"} <= set(result.checked)


def test_successful_checkers_recorded_in_order():
    result = verify("plain text, nothing to flag", VerifyContext())
    assert result.checked == ["imports", "flags", "links", "counts"]


# ---------------------------------------------------------------------------
# Semantic orchestration (_run_semantic)
# ---------------------------------------------------------------------------
class _FakeJudge:
    def __init__(self, verdict: SemanticVerdict):
        self._verdict = verdict
        self.calls: list[dict] = []

    def score(self, query, answer, passages):
        self.calls.append({"query": query, "answer": answer, "passages": passages})
        return self._verdict


def test_semantic_disabled_does_not_invoke_judge():
    judge = _FakeJudge(SemanticVerdict(faithful=False, issues=["x"]))
    ctx = VerifyContext(judge=judge, semantic=False)
    result = verify("content", ctx)
    assert result.semantic_ran is False
    assert judge.calls == []
    assert all(f.kind is not FindingKind.SEMANTIC for f in result.findings)


def test_semantic_faithful_produces_no_findings_and_sets_flag():
    judge = _FakeJudge(SemanticVerdict(faithful=True))
    ctx = VerifyContext(judge=judge, semantic=True)
    result = verify("the generated answer", ctx)
    assert result.semantic_ran is True
    assert [f for f in result.findings if f.kind is FindingKind.SEMANTIC] == []
    # The content is forwarded as the answer.
    assert judge.calls[0]["answer"] == "the generated answer"


def test_semantic_unfaithful_emits_one_error_per_issue():
    judge = _FakeJudge(SemanticVerdict(faithful=False, issues=["claim A", "claim B"]))
    ctx = VerifyContext(judge=judge, semantic=True)
    result = verify("content", ctx)
    sem = [f for f in result.findings if f.kind is FindingKind.SEMANTIC]
    assert [f.detail for f in sem] == ["claim A", "claim B"]
    assert all(f.severity == "error" for f in sem)
    assert result.ok is False


def test_semantic_requested_without_judge_warns():
    ctx = VerifyContext(semantic=True)  # no judge
    result = verify("content", ctx)
    sem = [f for f in result.findings if f.kind is FindingKind.SEMANTIC]
    assert len(sem) == 1
    assert sem[0].severity == "warning"
    assert result.semantic_ran is False


def test_semantic_judge_raising_degrades_to_warning():
    class _Raising:
        def score(self, query, answer, passages):
            raise RuntimeError("judge down")

    ctx = VerifyContext(judge=_Raising(), semantic=True)
    result = verify("content", ctx)
    sem = [f for f in result.findings if f.kind is FindingKind.SEMANTIC]
    assert len(sem) == 1
    assert sem[0].severity == "warning"
    assert "judge down" in sem[0].detail


# ---------------------------------------------------------------------------
# Link checker branches
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "target",
    ["http://example.com", "https://example.com/x", "mailto:a@b.com", "#anchor"],
)
def test_links_external_and_anchor_are_skipped(target):
    links = [MarkdownLink(text="t", target=target, line=1)]
    assert check_links(links, project_root=Path("/nonexistent")) == []


def test_links_missing_project_root_is_warning_not_error(tmp_path):
    links = [MarkdownLink(text="doc", target="docs/x.md", line=3)]
    findings = check_links(links, project_root=None)
    assert len(findings) == 1
    assert findings[0].severity == "warning"
    assert findings[0].kind is FindingKind.DEAD_LINK
    assert findings[0].location == "line 3"


def test_links_existing_file_passes_and_anchor_is_stripped(tmp_path):
    (tmp_path / "guide.md").write_text("x", encoding="utf-8")
    links = [MarkdownLink(text="g", target="guide.md#section", line=1)]
    assert check_links(links, project_root=tmp_path) == []


def test_links_dead_file_is_error(tmp_path):
    links = [MarkdownLink(text="g", target="missing.md", line=2)]
    findings = check_links(links, project_root=tmp_path)
    assert len(findings) == 1
    assert findings[0].severity == "error"
    assert "missing.md" in findings[0].detail


def test_links_traversal_outside_root_is_warning_even_if_file_exists(tmp_path):
    # ../-escapes can hit a real file on disk (e.g. /etc/passwd) — that must
    # not read as a verified project link. Unverifiable -> warning, never
    # a silent pass.
    outside = tmp_path / "outside.md"
    outside.write_text("x", encoding="utf-8")
    root = tmp_path / "project"
    root.mkdir()
    links = [MarkdownLink(text="up", target="../outside.md", line=1)]
    findings = check_links(links, project_root=root)
    assert len(findings) == 1
    assert findings[0].severity == "warning"
    assert "outside project_root" in findings[0].detail


def test_links_site_absolute_target_is_root_relative(tmp_path):
    # /docs/page.md means "from the project root" in generated docs — it must
    # be resolved under project_root, not against the filesystem root.
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "page.md").write_text("x", encoding="utf-8")
    assert check_links([MarkdownLink(text="p", target="/docs/page.md", line=1)], tmp_path) == []

    findings = check_links([MarkdownLink(text="pw", target="/etc/passwd", line=1)], tmp_path)
    assert len(findings) == 1
    assert findings[0].severity == "error"  # root/etc/passwd does not exist


# ---------------------------------------------------------------------------
# Flag checker branches
# ---------------------------------------------------------------------------
def test_flag_present_in_cached_help_is_clean():
    findings = check_flags(
        "Use `tool` `--verbose` now.",
        help_commands={"tool": "--verbose  be loud\n"},
        allowed_help_cmds=frozenset(),
    )
    assert findings == []


def test_flag_absent_from_cached_help_is_error():
    findings = check_flags(
        "Use `tool` `--ghost` now.",
        help_commands={"tool": "--verbose  be loud\n"},
        allowed_help_cmds=frozenset(),
    )
    assert len(findings) == 1
    assert findings[0].severity == "error"
    assert "--ghost" in findings[0].detail


def test_flag_for_unknown_command_is_warning():
    findings = check_flags(
        "Pass `mystery` `--flag`.",
        help_commands={},
        allowed_help_cmds=frozenset(),
    )
    assert len(findings) == 1
    assert findings[0].severity == "warning"


def test_missing_allowed_command_degrades_per_flag_not_per_checker():
    # One allow-listed-but-missing binary must not abort the checker: its flag
    # yields a warning while the cached-help flag is still verified (error).
    findings = check_flags(
        "Run `no_such_cmd_zzz` `--whatever`; also try `tool` `--ghost`.",
        help_commands={"tool": "--verbose  be loud\n"},
        allowed_help_cmds=frozenset(["no_such_cmd_zzz"]),
    )
    severities = {f.evidence: f.severity for f in findings}
    assert severities["`--whatever`"] == "warning"
    assert severities["`--ghost`"] == "error"


def test_get_help_missing_binary_returns_none_instead_of_raising():
    assert _get_help("no_such_cmd_zzz", {}, frozenset(["no_such_cmd_zzz"])) is None


def test_guess_command_picks_nearest_non_flag_token():
    assert _guess_command("run the `tool` ") == "tool"
    assert _guess_command("nothing useful ") == "useful"
    assert _guess_command("") == "unknown"


def test_get_help_cached_beats_subprocess():
    assert _get_help("x", {"x": "cached help"}, frozenset(["x"])) == "cached help"


def test_get_help_not_allowed_returns_none():
    assert _get_help("rm", {}, frozenset()) is None


def test_get_help_allowed_command_shells_out():
    # The current interpreter is guaranteed present and prints usage to --help.
    help_text = _get_help(sys.executable, {}, frozenset([sys.executable]))
    assert help_text is not None
    assert "usage" in help_text.lower()


# ---------------------------------------------------------------------------
# Import checker branches
# ---------------------------------------------------------------------------
def test_unrunnable_env_python_degrades_per_import_not_per_checker():
    # A bad interpreter path must not abort the checker: every import gets its
    # own "could not be verified" warning instead of one checker-level failure.
    fences = [CodeFence(language="python", content="import os\nimport sys\n", line=1)]
    findings = check_imports(fences, env_python="/no/such/python-zzz")
    assert len(findings) == 2
    assert all(f.severity == "warning" for f in findings)
    assert all("could not be verified" in f.detail for f in findings)


def test_bare_fence_imports_are_checked():
    fences = [CodeFence(language="", content="import definitely_fake_bare_zzz\n", line=1)]
    findings = check_imports(fences, env_python=sys.executable)
    assert len(findings) == 1
    assert findings[0].severity == "error"
    assert "definitely_fake_bare_zzz" in findings[0].detail


def test_bare_fence_non_python_is_skipped():
    fences = [CodeFence(language="", content="$ pip install attune-verify\n", line=1)]
    assert check_imports(fences, env_python=sys.executable) == []


def test_repeated_imports_resolved_once_per_call(monkeypatch):
    import attune_verify.checkers.imports as imports_mod

    calls = []
    real_run = imports_mod.subprocess.run

    def counting_run(*args, **kwargs):
        calls.append(args[0])
        return real_run(*args, **kwargs)

    monkeypatch.setattr(imports_mod.subprocess, "run", counting_run)
    fences = [
        CodeFence(language="python", content="import os\nimport os.path\n", line=1),
        CodeFence(language="python", content="import os\n", line=5),
    ]
    findings = check_imports(fences, env_python=sys.executable)
    assert findings == []
    # os appears twice but resolves once; os.path is distinct.
    assert len(calls) == 2


# ---------------------------------------------------------------------------
# Extractors: line numbers, language defaulting, context windows
# ---------------------------------------------------------------------------
def test_extract_code_fences_language_and_line():
    content = "intro\n\n```python\nimport os\n```\n"
    fences = extract_code_fences(content)
    assert len(fences) == 1
    assert fences[0].language == "python"
    assert fences[0].line == 3
    assert "import os" in fences[0].content


def test_extract_code_fences_blank_language_stays_empty():
    # "" (not "text") so the import checker's bare-fence branch can fire.
    fences = extract_code_fences("```\nplain\n```\n")
    assert fences[0].language == ""


def test_extract_code_fences_with_info_string():
    # ```python title="ex.py" — the info string must not hide the fence.
    fences = extract_code_fences('```python title="ex.py"\nimport os\n```\n')
    assert len(fences) == 1
    assert fences[0].language == "python"
    assert "import os" in fences[0].content


def test_extract_links_captures_text_target_and_line():
    links = extract_links("a\n[label](path/to.md)\n")
    assert len(links) == 1
    assert links[0].text == "label"
    assert links[0].target == "path/to.md"
    assert links[0].line == 2


def test_extract_numeric_claims_skips_single_digits_and_keeps_context():
    claims = extract_numeric_claims("there are 5 cats but 42 dogs around here")
    values = [c.value for c in claims]
    assert 5 not in values  # single digit skipped
    assert 42 in values
    claim = next(c for c in claims if c.value == 42)
    assert "dogs" in claim.context


def test_extract_numeric_claims_line_numbers():
    claims = extract_numeric_claims("intro line\nthen 42 here\n")
    assert len(claims) == 1
    assert claims[0].line == 2


# ---------------------------------------------------------------------------
# Counts: callable sources (a documented feature, otherwise untested)
# ---------------------------------------------------------------------------
def test_count_source_callable_is_resolved():
    claims = [NumericClaim(value=7, context="there are 7 plugins", line=1)]
    # Source disagrees (returns 9) so the claim must be flagged — proving the
    # callable was actually invoked, not compared as a function object.
    findings = check_counts(claims, count_sources={"plugins": lambda: 9})
    assert len(findings) == 1
    assert findings[0].kind is FindingKind.COUNT_MISMATCH
    assert "9" in findings[0].detail


def test_count_label_matches_on_word_boundary_only():
    # "test" must not match inside "latest" — that false-positived clean docs.
    claims = [NumericClaim(value=99, context="get the latest 99 release notes", line=1)]
    assert check_counts(claims, count_sources={"test": 50}) == []
    # A leading boundary still allows plural drift: "widget" matches "widgets".
    claims = [NumericClaim(value=99, context="there are 99 widgets here", line=1)]
    assert len(check_counts(claims, count_sources={"widget": 12})) == 1


def test_year_near_label_is_skipped_unless_adjacent():
    # A year with a source keyword merely nearby is a date, not a count.
    claims = [NumericClaim(value=2026, context="released 2026 versions of the widgets", line=1)]
    assert check_counts(claims, count_sources={"widgets": 12}) == []
    # But "2026 widgets" IS a widget count and must still be compared.
    claims = [NumericClaim(value=2026, context="there are 2026 widgets in stock", line=1)]
    findings = check_counts(claims, count_sources={"widgets": 12})
    assert len(findings) == 1
    assert findings[0].severity == "error"


def test_year_guard_boundaries():
    # Outside 1900-2099 the window match suffices; inside it needs adjacency.
    for value, expected_findings in ((1899, 1), (1900, 0), (2099, 0), (2100, 1)):
        claims = [
            NumericClaim(value=value, context=f"released {value} builds of the widgets", line=1)
        ]
        assert len(check_counts(claims, count_sources={"widgets": 12})) == expected_findings


def test_count_source_callable_matching_value_is_clean():
    claims = [NumericClaim(value=9, context="there are 9 plugins", line=1)]
    assert check_counts(claims, count_sources={"plugins": lambda: 9}) == []


# ---------------------------------------------------------------------------
# VerificationError message
# ---------------------------------------------------------------------------
def test_verification_error_lists_only_error_kinds():
    result = VerifyResult(
        findings=[
            Finding(kind=FindingKind.DEAD_LINK, detail="d", evidence="e", severity="error"),
            Finding(kind=FindingKind.UNKNOWN_FLAG, detail="w", evidence="e", severity="warning"),
        ]
    )
    err = VerificationError(result)
    msg = str(err)
    assert "dead_link" in msg
    assert "unknown_flag" not in msg  # warnings excluded
