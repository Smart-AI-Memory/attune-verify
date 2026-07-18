# Changelog

All notable changes to attune-verify are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
