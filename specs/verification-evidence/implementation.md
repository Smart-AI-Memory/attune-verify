# Implementation handoff

Date: 2026-09-10. Repository: attune-verify.
Base: 3b9191651ebbd7030d93cd14db009d9cb38f14c8 (0.5.0).
Branch: codex/verify-evidence-pipeline.
Worktree: /private/tmp/attune-verify-opportunities.

Patrick authorized committing this implementation on 2026-09-10.
The implementation is prepared on the branch above for review/integration.
The original /Users/patrickroebuck/attune-verify checkout was verified clean and
was not modified. No release, push, paid model call or version bump occurred.

## Result

The five phases in plan.md are implemented. Legacy verify/VerifyContext/ok and
error-only raise_if_failed remain usable. The strict policy explicitly rejects
unknown supported claims and empty verification. The CLI provides declared
context, versioned JSON reports and exit codes. The bounded evidence pilot
connects Python import claims to document lines and artifact fingerprints.

A code-review follow-up caught complex shell spans being attributed to nearby
prose; these now remain unknown. Receipt capture runs import checks only, so
it never invokes an unrelated semantic judge or count provider.

## Verification

- Original baseline: 173 tests passed before implementation.
- Five new accuracy regressions failed before their repairs, then passed.
- Final full suite: 269 passed, including the original 55-case synthetic
  precision/recall corpus gate. Measured line coverage: 95% (907/952 statements).
  `receipts/tests.txt` is the actual pytest coverage output.
- Mutation gate passed: 1,986/2,581 killed = 76.9%, above the unchanged 75%
  threshold. There were 2,597 generated mutants: 595 survived, 11 had no tests,
  and 5 timed out. The existing gate excludes no-test and timeout outcomes;
  these are not claimed as kills. `receipts/mutation.json` records final stats.
  After adding report-contract assertions, surviving mutants were explicitly
  rerun; previously killed results were retained. Subprocess CLI boundary tests
  skip only inside mutmut's generated tree because its instrumentation cannot
  initialize in a temporary cwd; CLI mutation coverage uses in-process tests.
- Ruff passed for src, tests and scripts/wheel_smoke.py; Black check passed for
  the same files; git diff --check passed.
- scripts/wheel_smoke.py built the wheel, installed it into a fresh environment,
  and exercised API imports, python-module CLI, console entry point, receipt
  capture and impact from outside the checkout. A checkout receipt requested
  rechecking in the installed environment; an installed receipt remained stable.
  `receipts/wheel.txt` records the actual run.
- Source modification, module removal, document alteration/removal, path escape,
  symlink output and repository metadata protection have executable tests.
- Real-document seed evaluation: one true positive, one true negative, one
  unlabeled case; human_validated_metrics remains null. The seed is too small
  to support a field accuracy claim. `evaluation/latest-machine-report.json`
  records this run, not an independent human benchmark.

## Limits and next integration step

Review the branch diff, then push in the owning repository workflow
and wait for the complete CI matrix (Windows and other Python versions have not
been run locally). Local verification used macOS/Python 3.11.14. Build smoke uses
platform-specific interpreter/entry-point paths and runs in every existing CI
matrix lane.

The optional attune-rag adapter was exercised with owned result fixtures, not a
live paid model. The import child executes trusted installed package initializers;
it is not a sandbox. Fingerprints do not model every transitive dependency or
prove runtime correctness. External URLs, fragments, relative/wildcard imports,
and unsupported prose remain outside positive verification.

Expand the real-document corpus and obtain independent human adjudication before
making field-accuracy claims. General evidence graphs and automatic regeneration
are follow-up product decisions, not implied by this pilot.
