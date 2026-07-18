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
        content="Run `mytool` `--verbose` for detailed output.",
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
        content="Pass `mytool` `--nonexistent` to enable it.",
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
)
