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
    strip_code_fences,
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
    ctx = VerifyContext(judge=judge, semantic=True, passages="the source passage")
    result = verify("the generated answer", ctx)
    assert result.semantic_ran is True
    assert [f for f in result.findings if f.kind is FindingKind.SEMANTIC] == []
    # The content is the answer; the declared passages are the ground truth.
    assert judge.calls[0]["answer"] == "the generated answer"
    assert judge.calls[0]["passages"] == "the source passage"


def test_semantic_unfaithful_emits_one_error_per_issue():
    judge = _FakeJudge(SemanticVerdict(faithful=False, issues=["claim A", "claim B"]))
    ctx = VerifyContext(judge=judge, semantic=True, passages="the source passage")
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
    assert "no judge" in sem[0].detail
    assert result.semantic_ran is False


def test_semantic_judge_failing_protocol_check_names_the_judge():
    # A judge that IS provided but lacks score() must not be reported as
    # "no judge was provided" — the message names the failing object.
    class _NotAJudge:
        pass

    ctx = VerifyContext(judge=_NotAJudge(), semantic=True, passages="src")
    result = verify("content", ctx)
    sem = [f for f in result.findings if f.kind is FindingKind.SEMANTIC]
    assert len(sem) == 1
    assert sem[0].severity == "warning"
    assert "does not satisfy the Judge protocol" in sem[0].detail
    assert "_NotAJudge" in sem[0].detail
    assert result.semantic_ran is False


def test_semantic_without_passages_warns_and_skips_judge():
    # Judging content against itself is vacuous — with no passages the
    # judge must not be called at all.
    judge = _FakeJudge(SemanticVerdict(faithful=True))
    ctx = VerifyContext(judge=judge, semantic=True)  # no passages
    result = verify("content", ctx)
    sem = [f for f in result.findings if f.kind is FindingKind.SEMANTIC]
    assert len(sem) == 1
    assert sem[0].severity == "warning"
    assert "passages" in sem[0].detail
    assert result.semantic_ran is False
    assert judge.calls == []


def test_semantic_judge_raising_degrades_to_warning():
    class _Raising:
        def score(self, query, answer, passages):
            raise RuntimeError("judge down")

    ctx = VerifyContext(judge=_Raising(), semantic=True, passages="src")
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


def test_links_percent_encoded_target_resolves_to_the_real_file(tmp_path):
    # A file whose name has a space is linked as %20; checking that literally
    # flagged a file that exists.
    (tmp_path / "my file.md").write_text("x", encoding="utf-8")
    assert check_links([MarkdownLink(text="d", target="my%20file.md", line=1)], tmp_path) == []


def test_links_percent_encoded_dead_target_still_flagged(tmp_path):
    # Decoding must not cost recall.
    findings = check_links([MarkdownLink(text="d", target="missing%20file.md", line=1)], tmp_path)
    assert len(findings) == 1
    assert findings[0].severity == "error"


def test_links_literal_percent_in_filename_still_resolves(tmp_path):
    # The raw form is tried first, so a file genuinely named 'a%20b.md'
    # resolves and is not mistaken for an encoded 'a b.md'.
    (tmp_path / "a%20b.md").write_text("x", encoding="utf-8")
    assert check_links([MarkdownLink(text="d", target="a%20b.md", line=1)], tmp_path) == []


def test_links_percent_encoded_traversal_is_still_caught(tmp_path):
    # Decoding must not open an escape hatch out of the declared boundary.
    outside = tmp_path / "outside.md"
    outside.write_text("x", encoding="utf-8")
    root = tmp_path / "project"
    root.mkdir()
    findings = check_links([MarkdownLink(text="up", target="%2e%2e/outside.md", line=1)], root)
    assert len(findings) == 1
    assert findings[0].severity == "warning"
    assert "outside project_root" in findings[0].detail


def test_links_balanced_parens_in_target_are_not_truncated(tmp_path):
    # '[^)]+' stopped at the first ')', checking 'docs/a(1' instead.
    (tmp_path / "a(1).md").write_text("x", encoding="utf-8")
    links = extract_links("See [the doc](a(1).md).")
    assert [link.target for link in links] == ["a(1).md"]
    assert check_links(links, project_root=tmp_path) == []


# ---------------------------------------------------------------------------
# Flag checker branches
# ---------------------------------------------------------------------------
_TAR_HELP = {"tar": "Usage: tar\n  -x, --extract\n  -z, --gzip\n  -f, --file F\n  -v, --verbose\n"}


def _flags(content, help_map=None):
    return check_flags(content, help_map or _TAR_HELP, frozenset())


@pytest.mark.parametrize(
    "content,help_map",
    [
        ("`tar -v`", None),  # single letter, known
        ("`tar -xzf a.tgz`", None),  # cluster, every letter known
        ("`find -name '*.py'`", {"find": "Usage: find\n  -name PAT\n  -type T\n"}),
        ("`make -j4`", {"make": "Usage: make\n  -j N, --jobs N\n"}),  # attached value
    ],
)
def test_short_flag_readings_that_verify_are_clean(content, help_map):
    assert _flags(content, help_map) == []


def test_short_single_letter_flag_absent_is_an_error():
    # Unambiguous: '-q' is that flag or nothing.
    findings = _flags("`tar -q`")
    assert [(f.severity, "-q" in f.detail) for f in findings] == [("error", True)]


@pytest.mark.parametrize(
    "content,help_map",
    [
        ("`tar -xqf a.tgz`", None),  # cluster with an unknown letter
        ("`find -nope`", {"find": "Usage: find\n  -name PAT\n"}),  # single-dash long
        ("`make -z9`", {"make": "Usage: make\n  -j N\n"}),  # attached value, unknown
    ],
)
def test_ambiguous_short_flag_degrades_to_warning_not_error(content, help_map):
    # '-xzf' may be a cluster, '-name' a single-dash long option, '-j4' a flag
    # with an attached value. Calling an unresolved reading refuted would risk
    # a false error on a real flag — unverifiable, so warn.
    findings = _flags(content, help_map)
    assert len(findings) == 1
    assert findings[0].severity == "warning"


@pytest.mark.parametrize(
    "content",
    [
        "`tar --threshold -5`",  # negative number argument
        "`cat -`",  # bare dash (stdin)
        "`tar -- -x`",  # end-of-options separator
        "Use `my-tool` for this.",  # hyphenated word
        "`tar -f /path/to-file`",  # hyphen inside a path
    ],
)
def test_tokens_that_are_not_short_flags(content):
    # Each of these would become a false positive if the token pattern were
    # any looser. '--threshold' is real here, so only non-flag tokens remain.
    assert [f for f in _flags(content) if "-5" in f.detail or "-x" in f.detail] == []


def test_short_flag_does_not_verify_against_a_longer_flag():
    # '-v' is a substring of '--verbose' and a suffix of '--v'; neither means
    # the command has a '-v'.
    for help_text in ("Usage: t\n  --verbose  Be loud\n", "Usage: t\n  --v  odd\n"):
        findings = check_flags("`t -v`", {"t": help_text}, frozenset())
        assert [f.severity for f in findings] == ["error"], help_text


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


def test_extract_code_fences_indented_under_list_item():
    # The fence's own indent must be stripped, or the body fails ast.parse
    # and every import inside it goes unchecked.
    content = "1. Then:\n\n   ```python\n   import os\n   x = 1\n   ```\n"
    fences = extract_code_fences(content)
    assert len(fences) == 1
    assert fences[0].language == "python"
    assert fences[0].content == "import os\nx = 1\n"
    assert fences[0].line == 3


def test_extract_code_fences_tilde_fence():
    fences = extract_code_fences("~~~python\nimport os\n~~~\n")
    assert len(fences) == 1
    assert fences[0].language == "python"
    assert fences[0].content == "import os\n"


def test_extract_code_fences_marker_kinds_do_not_close_each_other():
    # A ``` line inside a ~~~ fence is body, not a closing marker.
    fences = extract_code_fences("~~~\nnot a fence: ```\n~~~\n")
    assert len(fences) == 1
    assert fences[0].content == "not a fence: ```\n"


def test_extract_code_fences_longer_closing_run_closes():
    # CommonMark: the closing run must be at least as long as the opening one.
    fences = extract_code_fences("````python\nimport os\n`````\n")
    assert len(fences) == 1
    assert fences[0].content == "import os\n"


def test_extract_code_fences_unclosed_fence_is_not_a_fence():
    # Otherwise the "body" is the rest of the document and prose gets checked
    # as code.
    assert extract_code_fences("```python\nimport os\nand then prose.\n") == []


def test_extract_code_fences_inline_code_span_does_not_open_a_fence():
    # A backtick fence's info string may not contain a backtick — otherwise a
    # line-leading ```span``` swallows the prose after it as a fence body.
    assert extract_code_fences("```code``` is written inline.\nprose\n```\n") == []


def test_extract_code_fences_tilde_info_string_may_contain_a_backtick():
    # The backtick rule is specific to backtick fences.
    fences = extract_code_fences("~~~python `note`\nimport os\n~~~\n")
    assert len(fences) == 1
    assert fences[0].language == "python"


def test_strip_code_fences_blanks_lines_without_moving_prose():
    content = "before\n```bash\nmytool --x\n```\nafter\n"
    stripped = strip_code_fences(content)
    assert "mytool" not in stripped
    assert stripped.count("\n") == content.count("\n")
    assert stripped.splitlines()[0] == "before"
    assert stripped.splitlines()[4] == "after"


def test_extract_links_skips_code_spans_and_fences_but_keeps_line_numbers():
    content = (
        "intro\n"
        "Write it as `[text](example.md)` in the body.\n"
        "```markdown\n[shown](fenced.md)\n```\n"
        "See [the doc](real.md).\n"
    )
    links = extract_links(content)
    assert [(link.target, link.line) for link in links] == [("real.md", 6)]


@pytest.mark.parametrize("ticks", ["`", "``", "```"])
def test_extract_links_skips_spans_of_any_delimiter_width(ticks):
    # A doubled delimiter is how a span containing backticks is written; a
    # single-backtick rule masked its edges and left the middle exposed.
    content = f"Write it as {ticks}[shown](example.md){ticks} — see [the doc](real.md)."
    assert [link.target for link in extract_links(content)] == ["real.md"]


def test_extract_links_span_containing_backticks_is_masked_whole():
    content = "Inline ``code with `ticks` inside`` then [the doc](real.md)."
    assert [link.target for link in extract_links(content)] == ["real.md"]


# ---------------------------------------------------------------------------
# Reference-style links: the three CommonMark forms, definitions, footnotes
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "content",
    [
        "See [the doc][guide].\n\n[guide]: docs/a.md\n",  # full
        "See [guide][].\n\n[guide]: docs/a.md\n",  # collapsed
        "See [guide].\n\n[guide]: docs/a.md\n",  # shortcut
        'See [d][g].\n\n[g]: docs/a.md "Read me"\n',  # definition with title
        "See [d][g].\n\n[g]: <docs/a.md>\n",  # angle-bracket definition
        "See [The  Guide][].\n\n[the guide]: docs/a.md\n",  # case + whitespace
        "See [d][g].\n\n   [g]: docs/a.md\n",  # 3-space indented definition
        "1. See [d][g].\n\n    [g]: docs/a.md\n",  # definition under a list item
    ],
)
def test_reference_link_forms_resolve_to_the_definition(content):
    assert [link.target for link in extract_links(content)] == ["docs/a.md"]


def test_reference_link_first_definition_wins():
    content = "See [d][g].\n\n[g]: docs/first.md\n[g]: docs/second.md\n"
    assert [link.target for link in extract_links(content)] == ["docs/first.md"]


def test_reference_link_line_number_is_the_reference_not_the_definition():
    content = "intro\nprose\n\nSee [d][g].\n\n[g]: docs/a.md\n"
    assert [link.line for link in extract_links(content)] == [4]


def test_definition_inside_a_fence_does_not_define():
    # A renderer does not read definitions out of a code block, so the
    # reference is genuinely undefined.
    content = "See [d][g].\n\n```\n[g]: docs/a.md\n```\n"
    links = extract_links(content)
    assert [(link.target, link.label) for link in links] == [(None, "g")]


def test_undefined_explicit_reference_is_an_error(tmp_path):
    links = extract_links("See [the doc][guide].")
    findings = check_links(links, project_root=tmp_path)
    assert len(findings) == 1
    assert findings[0].severity == "error"
    assert "guide" in findings[0].detail
    # Evidence must be the syntax the reader can find in their document.
    assert findings[0].evidence == "[the doc][guide]"


def test_undefined_shortcut_reference_is_ordinary_prose(tmp_path):
    # Flagging these would false-positive on any bracketed text.
    links = extract_links("Handle the [3] case and the [TODO] items.")
    assert links == []
    assert check_links(links, project_root=tmp_path) == []


@pytest.mark.parametrize(
    "content",
    [
        "Claim.[^1]\n\n[^1]: Sourced\n",  # short body reads as a target
        "Claim.[^1]\n\n[^1]: Sourced from the docs\n",
    ],
)
def test_footnotes_are_not_link_references(content, tmp_path):
    assert extract_links(content) == []


def test_reference_and_inline_links_coexist(tmp_path):
    content = "See [a](docs/one.md) and [b][g].\n\n[g]: docs/two.md\n"
    assert [link.target for link in extract_links(content)] == [
        "docs/one.md",
        "docs/two.md",
    ]


def test_reference_link_inside_a_code_span_is_skipped():
    content = "Write `[d][g]` here.\n\n[g]: docs/a.md\n"
    assert extract_links(content) == []


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
