"""Corpus cases: labeled clean + hallucinated content.

Each :class:`CorpusCase` is self-contained: it declares the content to verify,
the truth boundaries needed to verify it (files to materialize, pre-captured
help text, count sources), and the ground-truth error findings expected.

Determinism rules:
- Import cases use the standard library (real) vs obviously-fake names so the
  result never depends on the surrounding pip environment.
- Flag cases supply pre-captured ``help_commands`` so no subprocess runs.
- Link cases declare ``files`` the harness materializes under a tmp project_root.
- Count cases supply ``count_sources`` inline.

``label`` documents intent: ``clean`` (no error findings expected),
``hallucinated`` (errors expected), or ``evasion`` (a hallucination crafted to
slip past a naive checker — these are the regression guards for known gaps).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from attune_verify.result import FindingKind


@dataclass(frozen=True)
class ExpectedFinding:
    """A ground-truth error finding the verifier must produce.

    Matched against a predicted finding when ``kind`` is equal and ``contains``
    appears in the finding's ``detail`` or ``evidence``.
    """

    kind: FindingKind
    contains: str


@dataclass(frozen=True)
class CorpusCase:
    """One labeled verification scenario."""

    name: str
    content: str
    label: str  # "clean" | "hallucinated" | "evasion"
    expected: tuple[ExpectedFinding, ...] = ()
    files: tuple[str, ...] = ()  # materialized under the tmp project_root
    help_commands: dict[str, str] = field(default_factory=dict)
    count_sources: dict[str, int] = field(default_factory=dict)


def _py(code: str) -> str:
    return f"```python\n{code}\n```\n"


CASES: tuple[CorpusCase, ...] = (
    # ---------------------------------------------------------------- clean
    CorpusCase(
        name="clean_imports",
        label="clean",
        content="Use the helpers:\n" + _py("import os\nfrom pathlib import Path\n"),
    ),
    CorpusCase(
        name="clean_real_submodule",
        label="clean",
        content=_py("from email.mime.text import MIMEText\nimport os.path\n"),
    ),
    CorpusCase(
        name="clean_relative_import",
        label="clean",
        # Relative imports cannot be resolved out of package context and must
        # never be flagged — regression guard for a false positive.
        content=_py("from .helpers import thing\nfrom . import sibling\n"),
    ),
    CorpusCase(
        name="clean_local_link",
        label="clean",
        content="See the [readme](README.md) for details.",
        files=("README.md",),
    ),
    CorpusCase(
        name="clean_external_link",
        label="clean",
        content="Docs live at [the site](https://example.com/docs).",
    ),
    CorpusCase(
        name="clean_count",
        label="clean",
        content="There are 12 widgets in the registry.",
        count_sources={"widgets": 12},
    ),
    CorpusCase(
        name="clean_flag",
        label="clean",
        # Realistic form: the whole command lives in ONE backtick span.
        content="Run `mytool --verbose` for detailed output.",
        help_commands={"mytool": "Options:\n  --verbose  Be loud\n  --help  Show help\n"},
    ),
    CorpusCase(
        name="clean_flag_bash_fence",
        label="clean",
        content="Run it:\n```bash\n$ mytool --verbose\n```\n",
        help_commands={"mytool": "Options:\n  --verbose  Be loud\n  --help  Show help\n"},
    ),
    # --------------------------------------------------------- hallucinated
    CorpusCase(
        name="fake_toplevel_import",
        label="hallucinated",
        content=_py("import definitely_not_a_real_pkg_zzz\n"),
        expected=(ExpectedFinding(FindingKind.UNRESOLVED_IMPORT, "definitely_not_a_real_pkg_zzz"),),
    ),
    CorpusCase(
        name="fake_submodule_import",
        label="hallucinated",
        # email is a real package; this submodule does not exist.
        content=_py("from email.totally_fake_submodule import Thing\n"),
        expected=(ExpectedFinding(FindingKind.UNRESOLVED_IMPORT, "email.totally_fake_submodule"),),
    ),
    CorpusCase(
        name="dead_local_link",
        label="hallucinated",
        content="See [the design doc](docs/design-that-does-not-exist.md).",
        expected=(ExpectedFinding(FindingKind.DEAD_LINK, "docs/design-that-does-not-exist.md"),),
    ),
    CorpusCase(
        name="count_mismatch",
        label="hallucinated",
        content="We support 99 languages out of the box.",
        count_sources={"languages": 5},
        expected=(ExpectedFinding(FindingKind.COUNT_MISMATCH, "99"),),
    ),
    CorpusCase(
        name="fake_flag",
        label="hallucinated",
        # Realistic form: the whole command lives in ONE backtick span — the
        # v0.2.2 extractor only matched a flag backticked alone, so this
        # (the most common way LLMs write commands) passed silently.
        content="Pass `mytool --nonexistent` to enable it.",
        help_commands={"mytool": "Options:\n  --verbose  Be loud\n  --help  Show help\n"},
        expected=(ExpectedFinding(FindingKind.UNKNOWN_FLAG, "--nonexistent"),),
    ),
    CorpusCase(
        name="clean_year_near_count_keyword",
        label="clean",
        # 2026 is a year, not a widget count — a keyword merely nearby must
        # not turn it into a COUNT_MISMATCH (regression for a false positive).
        content="Released 2026 versions of the widgets.",
        count_sources={"widgets": 12},
    ),
    CorpusCase(
        name="year_valued_count_still_checked",
        label="hallucinated",
        # A year-like value directly before the keyword IS a count claim and
        # must still be compared — the year guard must not cost recall here.
        content="There are 2026 widgets in stock.",
        count_sources={"widgets": 12},
        expected=(ExpectedFinding(FindingKind.COUNT_MISMATCH, "2026"),),
    ),
    # --------------------------------------------------------------- evasion
    CorpusCase(
        name="evasion_multi_import",
        label="evasion",
        # Only the first name is real; a naive checker that inspects names[0]
        # misses the fake second import.
        content=_py("import os, definitely_fake_xyz\n"),
        expected=(ExpectedFinding(FindingKind.UNRESOLVED_IMPORT, "definitely_fake_xyz"),),
    ),
    CorpusCase(
        name="evasion_substring_flag",
        label="evasion",
        # "--ver" is not a real flag; a substring check passes it because
        # "--verbose" contains it.
        content="Use `mytool` `--ver` to set the level.",
        help_commands={"mytool": "Options:\n  --verbose  Be loud\n  --help  Show help\n"},
        expected=(ExpectedFinding(FindingKind.UNKNOWN_FLAG, "--ver"),),
    ),
    CorpusCase(
        name="evasion_info_string_fence",
        label="evasion",
        # A fence with an info string (```python title="...") slipped past the
        # v0.2.1 extractor entirely, so anything inside went unchecked.
        content='```python title="ex.py"\nimport definitely_fake_info_pkg_zzz\n```\n',
        expected=(ExpectedFinding(FindingKind.UNRESOLVED_IMPORT, "definitely_fake_info_pkg_zzz"),),
    ),
    CorpusCase(
        name="evasion_bare_fence_import",
        label="evasion",
        # LLM output routinely omits the language tag; v0.2.1 mapped bare
        # fences to "text" so their imports were never checked.
        content="```\nimport definitely_fake_bare_pkg_zzz\n```\n",
        expected=(ExpectedFinding(FindingKind.UNRESOLVED_IMPORT, "definitely_fake_bare_pkg_zzz"),),
    ),
    CorpusCase(
        name="clean_bare_fence_shell",
        label="clean",
        # Bare fences with non-Python content must not be flagged — the
        # speculative parse skips anything that isn't valid Python.
        content="Install it:\n```\n$ pip install attune-verify\n```\n",
    ),
    CorpusCase(
        name="evasion_count_cross_contamination",
        label="evasion",
        # 12 matches the *modules* source globally, but the claim is about
        # tests (expected 50). A global-value-set check lets it pass.
        content="The suite ran 12 tests successfully.",
        count_sources={"tests": 50, "modules": 12},
        expected=(ExpectedFinding(FindingKind.COUNT_MISMATCH, "12"),),
    ),
    # ------------------------------------------------- 2026-08-10 audit fixes
    CorpusCase(
        name="clean_comma_grouped_count",
        label="clean",
        # "1,234" is ONE number. The v0.2.2 extractor grabbed the "234"
        # fragment and flagged it against tests=1234 (error false positive).
        content="The suite runs 1,234 tests on every push.",
        count_sources={"tests": 1234},
    ),
    CorpusCase(
        name="comma_grouped_count_mismatch",
        label="hallucinated",
        # Comma handling must not cost recall: a wrong grouped count is
        # still a mismatch.
        content="The suite runs 1,234 tests on every push.",
        count_sources={"tests": 999},
        expected=(ExpectedFinding(FindingKind.COUNT_MISMATCH, "1234"),),
    ),
    CorpusCase(
        name="comma_grouped_year_valued_count",
        label="hallucinated",
        # "2,026" is year-VALUED but comma-grouped — nobody writes a year
        # with a thousands separator, so it is a count and must be checked.
        content="There are 2,026 widgets in stock.",
        count_sources={"widgets": 12},
        expected=(ExpectedFinding(FindingKind.COUNT_MISMATCH, "2026"),),
    ),
    CorpusCase(
        name="clean_decimal_near_keyword",
        label="clean",
        # "94.53" is a decimal, not two counts — the v0.2.2 extractor split
        # it into 94 and 53 and flagged both against the source.
        content="Coverage sits at 94.53 percent across the tests.",
        count_sources={"tests": 50},
    ),
    CorpusCase(
        name="clean_version_number_near_keyword",
        label="clean",
        # The "10" in "Python 3.10" is a version component, not a module
        # count — a nearby source keyword must not turn it into a claim.
        content="Requires Python 3.10 to load the python modules.",
        count_sources={"python modules": 12},
    ),
    CorpusCase(
        name="short_label_count_mismatch",
        label="hallucinated",
        # v0.2.2 dropped label words of length <= 3, so an "api" source
        # could never match any claim — silently dead (false negative).
        content="The service exposes 42 api endpoints.",
        count_sources={"api": 3},
        expected=(ExpectedFinding(FindingKind.COUNT_MISMATCH, "42"),),
    ),
    CorpusCase(
        name="clean_short_label_boundary",
        label="clean",
        # Short labels match on exact word boundaries only — "api" must not
        # match inside "rapid" and drag unrelated numbers into the source.
        content="We shipped 42 rapid iterations this quarter.",
        count_sources={"api": 3},
    ),
    CorpusCase(
        name="clean_stopword_in_mixed_label",
        label="clean",
        # A short word in a MIXED label is usually a stopword: "of" must not
        # match ordinary prose and drag unrelated numbers into the source.
        # Short-word matching is a fallback for all-short labels only.
        content="Only 12 of the widgets remain in the box.",
        count_sources={"number of tests": 83},
    ),
    CorpusCase(
        name="mixed_label_long_word_still_matches",
        label="hallucinated",
        # The fallback rule must not cost recall: a mixed label still
        # matches on its long words.
        content="The suite ran 12 tests successfully.",
        count_sources={"number of tests": 83},
        expected=(ExpectedFinding(FindingKind.COUNT_MISMATCH, "12"),),
    ),
    CorpusCase(
        name="evasion_flag_in_bash_fence",
        label="evasion",
        # Flags inside ```bash fences were entirely unchecked in v0.2.2.
        content="Enable it:\n```bash\nmytool --nonexistent\n```\n",
        help_commands={"mytool": "Options:\n  --verbose  Be loud\n  --help  Show help\n"},
        expected=(ExpectedFinding(FindingKind.UNKNOWN_FLAG, "--nonexistent"),),
    ),
    CorpusCase(
        name="clean_link_with_title",
        label="clean",
        # Markdown title syntax: the title is not part of the path — v0.2.2
        # checked 'docs/a.md "Read me"' for existence and errored.
        content='See [the doc](docs/a.md "Read me") for details.',
        files=("docs/a.md",),
    ),
    CorpusCase(
        name="clean_link_angle_brackets",
        label="clean",
        content="See [the doc](<docs/a.md>) for details.",
        files=("docs/a.md",),
    ),
    CorpusCase(
        name="dead_link_with_title_still_flagged",
        label="hallucinated",
        # Title stripping must not cost recall: a dead path with a title is
        # still a dead link.
        content='See [the doc](docs/missing.md "Read me").',
        expected=(ExpectedFinding(FindingKind.DEAD_LINK, "docs/missing.md"),),
    ),
    CorpusCase(
        name="evasion_indented_fence_import",
        label="evasion",
        # A fence nested under a list item was invisible to the extractor in
        # v0.2.x, so every import inside it passed unchecked — the exact
        # silent-pass class this library exists to prevent, in the shape LLMs
        # write installation docs.
        content=(
            "1. Install the package.\n"
            "2. Then import it:\n"
            "\n"
            "   ```python\n"
            "   import totally_fake_pkg_xyz_2026\n"
            "   ```\n"
        ),
        expected=(ExpectedFinding(FindingKind.UNRESOLVED_IMPORT, "totally_fake_pkg_xyz_2026"),),
    ),
    CorpusCase(
        name="evasion_indented_fence_flag",
        label="evasion",
        # Same blind spot, flag side: an indented ```bash block under a step.
        content="1. Run it:\n\n   ```bash\n   mytool --nonexistent\n   ```\n",
        help_commands={"mytool": "Options:\n  --verbose  Be loud\n"},
        expected=(ExpectedFinding(FindingKind.UNKNOWN_FLAG, "--nonexistent"),),
    ),
    CorpusCase(
        name="evasion_tilde_fence_import",
        label="evasion",
        # ~~~ is a CommonMark fence the extractor never recognized.
        content="~~~python\nimport totally_fake_pkg_xyz_2026\n~~~\n",
        expected=(ExpectedFinding(FindingKind.UNRESOLVED_IMPORT, "totally_fake_pkg_xyz_2026"),),
    ),
    CorpusCase(
        name="clean_link_percent_encoded_space",
        label="clean",
        # A file whose name contains a space is linked as %20; checking the
        # literal string flagged a file that exists.
        content="See [the doc](docs/my%20file.md).",
        files=("docs/my file.md",),
    ),
    CorpusCase(
        name="dead_link_percent_encoded_still_flagged",
        label="hallucinated",
        # Decoding must not cost recall.
        content="See [the doc](docs/missing%20file.md).",
        expected=(ExpectedFinding(FindingKind.DEAD_LINK, "docs/missing%20file.md"),),
    ),
    CorpusCase(
        name="clean_link_syntax_shown_in_code_span",
        label="clean",
        # Docs that document link syntax were flagged for the example they
        # show; no renderer resolves a link inside a code span.
        content="Write it as `[text](docs/example.md)` in the body.",
    ),
    CorpusCase(
        name="clean_link_syntax_shown_in_fence",
        label="clean",
        content="Example:\n\n```markdown\n[text](docs/example.md)\n```\n",
    ),
    CorpusCase(
        name="dead_link_in_prose_beside_a_code_span_still_flagged",
        label="hallucinated",
        # Masking must not cost recall: a real link on the same line as an
        # example is still checked.
        content="Write it as `[text](target.md)` — see [the doc](docs/missing.md).",
        expected=(ExpectedFinding(FindingKind.DEAD_LINK, "docs/missing.md"),),
    ),
    CorpusCase(
        name="clean_reference_link_resolves",
        label="clean",
        content="See [the guide][guide] for details.\n\n[guide]: docs/a.md\n",
        files=("docs/a.md",),
    ),
    CorpusCase(
        name="dead_reference_link_target_flagged",
        label="hallucinated",
        # Reference links were entirely unchecked before 0.4.0 — a dead target
        # behind a label was a silent pass.
        content="See [the guide][guide].\n\n[guide]: docs/missing.md\n",
        expected=(ExpectedFinding(FindingKind.DEAD_LINK, "docs/missing.md"),),
    ),
    CorpusCase(
        name="undefined_reference_label_flagged",
        label="hallucinated",
        # An explicit reference with no definition renders literally — the
        # reader sees '[the guide][guide]', so the link never existed.
        content="See [the guide][guide] for details.",
        expected=(ExpectedFinding(FindingKind.DEAD_LINK, "guide"),),
    ),
    CorpusCase(
        name="clean_shortcut_reference_resolves",
        label="clean",
        content="See [guide] for details.\n\n[guide]: docs/a.md\n",
        files=("docs/a.md",),
    ),
    CorpusCase(
        name="clean_bracketed_prose_is_not_a_link",
        label="clean",
        # An undefined SHORTCUT is ordinary prose, not a broken link —
        # flagging it would false-positive on any bracketed text.
        content="Handle the [3] case and the [TODO] items before shipping.",
    ),
    CorpusCase(
        name="clean_footnote_is_not_a_link_reference",
        label="clean",
        # GFM footnotes share reference syntax exactly; a short footnote body
        # read as a target and flagged 'Sourced' as a missing file.
        content="The count is stable.[^1]\n\n[^1]: Sourced\n",
    ),
    CorpusCase(
        name="clean_link_balanced_parens",
        label="clean",
        # '[^)]+' truncated the target at the first ')', so 'docs/a(1).md'
        # was checked as 'docs/a(1' and flagged.
        content="See [the doc](docs/a(1).md).",
        files=("docs/a(1).md",),
    ),
)
