# Changelog

All notable changes to attune-verify are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Reference-style links are checked.** Only inline `[text](target)` links
  were resolved, so every reference form was a silent pass — a dead target
  behind a label went unreported. All three CommonMark forms now resolve
  against the document's `[label]: target` definitions: full
  `[text][label]`, collapsed `[text][]`, and shortcut `[text]`. Definitions
  are matched case-insensitively with whitespace collapsed, may carry a
  title or `<angle-bracket>` target, may be indented (including nested under
  a list item), and the first definition of a repeated label wins.
- **An explicit reference with no definition is an error.** `[text][label]`
  without a matching definition renders as literal text — the link does not
  exist, which is a refuted claim rather than an unverifiable one. Findings
  quote the reference form (`[text][label]`) rather than inline syntax the
  reader would not find in their document.

### Fixed

- **Undefined shortcut references are not links.** `[3]` and `[TODO]` in
  ordinary prose only become links when a definition exists, so an undefined
  shortcut is skipped rather than flagged — the bracketed-prose false
  positive that makes shortcut support worth having at all.
- **GFM footnotes are excluded.** A footnote shares reference syntax exactly:
  `[^1]` against `[^1]: Sourced` parsed as a link whose target was the
  footnote body, flagging `Sourced` as a missing file. The `^` namespace is
  no longer read as a link reference.
- **Definitions inside code fences no longer define.** A renderer does not
  read definitions out of a code block, so a reference that depends on one is
  correctly reported as undefined.

## [0.3.0] - 2026-08-11

**Beta.** The deterministic core is stable and the public API is now covered
by a compatibility promise (see the README status section). Two releases'
worth of accuracy work lands here: the 2026-08-10 audit fixes plus a
beta-review pass that closed two more silent false-negative classes in the
fence extractor and two link false positives.

### Changed

- **`Development Status :: 4 - Beta`** (was `2 - Pre-Alpha`). `verify`,
  `VerifyContext`, `VerifyResult`, `Finding`, `FindingKind`,
  `raise_if_failed` and the `Judge` protocol will not change shape without a
  deprecation in a minor release.

### Added

- **`py.typed`.** The package is fully annotated but shipped no PEP 561
  marker, so type checkers ignored it in downstream projects.
- **Packaging guards.** `__version__` and the `pyproject.toml` version are
  pinned equal by a test — the release flow bumps both by hand, and drift
  would ship a wheel whose metadata disagrees with the runtime value.
- **README:** a per-checker table of what each checker settles and which
  truth source it needs, plus an explicit known-limitations list.

### Fixed

- **Indented code fences are no longer invisible.** A fence nested under a
  list item — how LLMs routinely write install steps — matched nothing, so
  every import and shell flag inside one passed unchecked. The extractor is
  now a line scanner: it accepts a fence at any indentation and strips that
  indent from the body (uniformly indented code otherwise fails `ast.parse`,
  which was the silent skip). This was the largest remaining hole.
- **Tilde fences (`~~~`) are extracted.** CommonMark-legal and previously
  unrecognized — another silent pass.
- **Percent-encoded link targets resolve.** A link to a file whose name
  contains a space is written `docs/my%20file.md`; that was checked
  literally and flagged a file that exists. The raw form is still tried
  first, so a file genuinely named `a%20b.md` resolves, and a decoded
  target that escapes `project_root` is still caught.
- **Balanced parentheses in link targets are not truncated.**
  `[doc](docs/a(1).md)` was cut to `docs/a(1)` and flagged.
- **Link syntax shown as an example is no longer checked as a link.** A doc
  documenting its own conventions ("write it as `` `[text](target.md)` ``")
  was flagged for a target it never claimed existed — no renderer resolves a
  link inside a code span or fence. Links are now read from prose only —
  spans of any delimiter width, so a doubled delimiter around a span that
  itself contains backticks is masked whole rather than at its edges. Line
  numbers are unaffected, and a real link sharing a line with an example is
  still checked. Found by running verify over its own README.
- The fence scanner also enforces the rules the old regex ignored: an
  unclosed fence is not a fence (its body was the rest of the document), a
  closing run must match the opening character and length, and an inline
  ``` ```code``` ``` span no longer opens one.
- Stripping fences before the flag scan now blanks the lines in place
  rather than deleting them, so prose either side of a code block never
  becomes adjacent when the checker looks backwards for a command name.

### Fixed (2026-08-10 audit)

- **Comma-grouped numbers are one claim.** "1,234 tests" previously
  extracted the "234" fragment and flagged an error-severity count
  mismatch against `tests=1234`; `1,234` is now extracted as the single
  value 1234 (commas stripped). Grouped values also stay checked when
  year-valued — "2,026 widgets" is a count, never a year.
- **Decimals and version components are not counts.** "94.53" near a
  source keyword extracted 94 and 53 as separate claims and flagged both;
  the "10" in "Python 3.10" was flagged against a nearby source. Digit
  runs adjacent to a decimal point are now skipped.
- **Short count-source labels are no longer silently dead.** Label words
  of length ≤ 3 ("api", "eps") were dropped by the keyword filter, so
  those sources could never match any claim — a silent false negative.
  Short words now require an exact word-boundary match on both sides
  ("api" matches "api" but not "rapid"), and participate only when the
  label has no longer word — in a mixed label ("number of tests") a short
  word is usually a stopword, and letting "of" match ordinary prose would
  drag unrelated numbers into the source. Longer words keep the
  leading-boundary match so plural drift still hits.
- **Flags inside real command spans and shell fences are now checked.**
  The extractor only matched a flag backticked alone (`` `--flag` ``);
  the common form `` `mytool --flag` `` — the whole command in one span —
  matched nothing, despite a comment claiming it was handled, and flags
  inside ```` ```bash ```` fences were unchecked. Both are now extracted
  (fences: bash/sh/shell/console/zsh), with the command guessed from the
  span or line itself before falling back to preceding prose.
- **Markdown link titles no longer break path checks.**
  `[text](docs/a.md "Read me")` treated the whole `docs/a.md "Read me"`
  string as the path and errored even when the file exists. The optional
  title is stripped and `<angle-bracket>` targets are unwrapped; dead
  paths with titles are still flagged.
- **The semantic layer no longer judges content against itself.**
  `verify()` passed the generated content as its own source passages —
  vacuously faithful by construction. `VerifyContext` gains a `passages`
  field that is forwarded to the judge; when `semantic=True` with no
  passages, verify degrades gracefully (warning, judge not called).
- **The no-judge warning no longer misreports a bad judge.** A judge that
  was provided but fails the `Judge` protocol check was reported as "no
  judge was provided"; the message now names the failing object and the
  protocol mismatch.

### Changed (2026-08-10 audit)

- Import resolution passes the module name to the child interpreter via
  `argv` instead of f-string interpolation into the `-c` program —
  defense in depth (`ast` already guarantees identifier-safe names).
- Corpus flag cases use the realistic single-span form
  (`` `mytool --verbose` ``) instead of the unnatural split form; the
  split form remains covered by `evasion_substring_flag`.

## [0.2.2] - 2026-07-17

Accuracy + reliability patch from a full library review: five silent
false-negative classes closed, two false-positive classes stopped, and
the `[rag]` semantic layer works for the first time (its adapter read a
field attune-rag never had and crashed on every call).

### Fixed

- **rag adapter no longer crashes on every call.** It read
  `result.is_faithful`, a field attune-rag's `FaithfulnessResult` has never
  had (its verdict is score/claims-based), so the semantic layer always
  degraded to a warning. `faithful` is now derived from
  `unsupported_claims`; the adapter also raises a clear error when called
  from inside a running event loop instead of asyncio.run's generic one.
- **Years near a count keyword no longer false-positive.** "Released 2026
  versions of the widgets" flagged 2026 against the `widgets` source. Values
  in 1900–2099 are now compared only when the keyword directly follows the
  number ("2026 widgets" is still checked).
- **Count-source keywords match on a word boundary.** "test" no longer
  matches inside "latest" (plural drift still matches: "widget" ~ "widgets").
- **Link targets can no longer escape `project_root`.** `../`-traversal that
  happens to hit a real file outside the root previously passed silently; it
  now yields a warning (unverifiable as a project link). Site-absolute
  targets (`/docs/page.md`) are resolved under `project_root` instead of the
  filesystem root.
- `check_counts` docstring claimed unmatched claims yield warnings; they are
  (and were) silently skipped — the docstring now says so.
- **Fences with an info string are now extracted.** ` ```python title="ex.py" `
  previously matched nothing, so everything inside the fence went unchecked —
  a silent false negative for any MkDocs/Docusaurus-style generated doc.
- **Bare code fences are now import-checked.** LLM output routinely omits the
  language tag; bare fences were mapped to "text" and skipped entirely, so a
  fake import in an untagged fence passed silently. Untagged fences are now
  parsed speculatively — non-Python content fails `ast.parse` and is skipped,
  so no new false positives (guarded by corpus case `clean_bare_fence_shell`).
- **One broken command no longer aborts a whole checker.** An allow-listed
  `--help` command whose binary is missing (or times out) raised out of the
  flags checker, collapsing every other flag in the document into a single
  checker-level warning; same for a bad `env_python` in the import checker.
  Both now degrade per-flag / per-import (warning) and keep checking the rest.

### Added

- **`FindingKind.CHECKER_ERROR`** — checker infrastructure failures carry
  their own kind instead of repurposing `UNRESOLVED_IMPORT`.
- Import resolution is cached per `verify()` call — repeated imports of the
  same module across fences no longer re-launch the interpreter.
- `VerifyContext.judge` is typed `Optional[Judge]` (was `object`).
- CI now enforces `black --check` alongside ruff; the codebase is formatted.

## [0.2.1] - 2026-06-22

Verifier-accuracy fixes — `verify()` now catches three hallucination
classes it previously missed and stops one false positive. Surfaced by a
new labeled corpus + mutation-testing harness (dev-only, no runtime effect).

### Fixed

- **Import checker now flags every name in a multi-import.** `import os,
  fake_mod` previously checked only the first name, letting a fake hide
  behind a real one. All names are now resolved.
- **Flag checker uses whole-token matching.** A substring check passed a
  hallucinated `--ver` because real help contained `--verbose`; flags are
  now matched on a word boundary.
- **Count checker matches each claim to its own source.** Comparing against
  the global set of all source values let a claim pass on a coincidental
  match with an unrelated source (e.g. "12 tests" passing because some other
  source equalled 12). Each claim is now compared against the source its
  surrounding text names.
- **Relative imports are no longer false-flagged.** `from .helpers import x`
  cannot be resolved out of package context and is skipped.

### Added

- **Labeled verification corpus + precision/recall gate** (`tests/corpus/`):
  deterministic clean + hallucinated cases (including the three evasions
  above) scored on precision/recall, gated at ≥ 0.95 each.
- **Mutation testing** via `mutmut` (`scripts/mutation_gate.py`,
  `.github/workflows/mutation.yml`) — kill rate ≈ 80% on the deterministic
  core, gated at 0.75.
- **`tests.yml` CI** — the first real test workflow (matrix 3.10–3.13 on
  Linux + a macOS/Windows smoke), running ruff + pytest with coverage.
- Behavioral tests for the exception-isolation, semantic-orchestration,
  link/flag warning + subprocess, and extractor edge-case paths.

## [0.2.0] - 2026-06-09

### Changed

- **Import checker now resolves the FULL dotted module path.** v0.1.0
  checked only the top-level package, so a private submodule of an
  installed package (`from attune.ops._readers import X` where
  `attune` is installed but `attune.ops._readers` is not) passed
  silently — exactly the attune-author PR-#351 hallucination class.
  The checker now resolves the full path via `find_spec`, flagging the
  missing submodule. Fully-unknown top-level packages are still
  flagged as before. Brings parity with attune-author's `fact_check`
  `python_refs` resolution.

## [0.1.0] - 2026-06-09

Initial release — the generation fact-checker for the attune-* family.

### Added

- Deterministic core (`attune_verify.verify`) that checks the named
  entities in LLM-generated content actually exist, with zero LLM
  dependency: unresolved imports (`importlib.util.find_spec`), unknown
  CLI flags (vs gated `--help` capture), dead markdown links (vs the
  project root), and count mismatches (vs caller-supplied sources).
- `VerifyContext` — callers declare the truth boundaries (project root,
  env python, allow-listed `--help` commands, count sources); verify does
  the lookups. Generated code is never executed; only allow-listed CLIs
  are introspected.
- `VerifyResult` / `Finding` / `raise_if_failed()` — return-and-inspect by
  default, opt-in hard gate.
- Injected `Judge` protocol + `SemanticVerdict` for an optional semantic
  layer; deterministic resolution is authoritative and suppresses
  semantic false positives for entities it can resolve.
- `[rag]` extra — adapter over attune-rag's `FaithfulnessJudge` as a
  headless semantic judge.
- Regression fixture rebuilt from the attune-author #351 hallucinations
  (invented flag, private-module imports, dead cross-refs, wrong count,
  wrong route path) — verify flags each.
