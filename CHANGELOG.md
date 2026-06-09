# Changelog

All notable changes to attune-verify are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
