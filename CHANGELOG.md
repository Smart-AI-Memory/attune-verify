# Changelog

All notable changes to attune-verify are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
