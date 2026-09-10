# Reliability maintenance release: 0.6.1

This release repairs the reliability review's F1–F14 findings and settles the
semantic coverage boundary. Its acceptance target is observable behavior: retain
the supported claims, compare each with the intended source, preserve completed
evidence through local failures, and publish the distribution bytes that passed
installed checks.

The deterministic core retains zero runtime dependencies. The public error-only
`ok` behavior remains available; strict publication uses `passes()` or an explicit
`VerificationPolicy`. Additional verification categories and live model calls are
outside this maintenance release.

## Validation contract

The release evidence packet records execution status for the selected source and
artifacts. This document defines the required checks; workflow configuration and
test presence alone do not establish that they passed.

| Evidence | Release requirement |
|---|---|
| Full suite, lint, and corpus | Pass for the selected source and supported runtime matrix. |
| Complete mutation result | Valid nonempty evidence at the unchanged 75% threshold. |
| Exact wheel/sdist installed checks | Both distributions pass; retain their SHA-256 hashes. |
| Remote tests and mutation | Successful push-to-main runs for the exact full source SHA. |
| Human PyPI approval and publication | Required reviewer approves in Actions; verify published distribution hashes afterward. |

Never substitute a passing earlier checkout, a separately rebuilt wheel, or an
interim test count for the release packet.

## Review findings and regression evidence

The identifiers below retain the original review numbering. Test names identify
the assertions to inspect; a test's presence does not assert a fresh passing run.

| Review finding | Concrete regression or executable check | Release acceptance |
|---|---|---|
| **F1: output aliases overwrite inputs or repository metadata** | [test_reliability_cli.py](../tests/test_reliability_cli.py): `test_output_case_alias_preserves_input`, `test_output_case_alias_preserves_context`, `test_metadata_case_alias_is_rejected`; existing [test_security.py](../tests/test_security.py) | Reject equivalent input/metadata paths before mutation, exit 2, and preserve original bytes. Run actual case-alias cases on a case-insensitive filesystem; a skip is not proof of that platform behavior. |
| **F2: one malformed item erases other evidence** | [test_reliability_markdown.py](../tests/test_reliability_markdown.py): NUL link and oversized integer cases; [test_reliability_resolvers.py](../tests/test_reliability_resolvers.py): invalid UTF-8 help/imports and Python parse recursion; [test_reliability_counts.py](../tests/test_reliability_counts.py): `test_oversized_integer_retains_counts_before_and_after_it` | Retain refutations before and after the failing item, classify that item as unknown, and continue. A known refutation keeps legacy `ok` false. Syntax errors remain refuted. |
| **F3: an EOF-truncated Python fence disappears** | [test_reliability_markdown.py](../tests/test_reliability_markdown.py): `test_eof_fence_retains_code_and_original_line`, `test_truncating_rejected_python_does_not_promote_to_strict_success` | Retain the fence through EOF, preserve language and line, and keep rejected import claims after removing the closing marker. |
| **F4: valid nested links disappear from coverage** | [test_reliability_markdown.py](../tests/test_reliability_markdown.py): `test_nested_links_remain_in_denominator` | Nested link text and balanced destination parentheses retain both links and locations. Missing destinations refute; present destinations verify. One good link cannot hide a missing extracted neighbor. |
| **F5: flag prefixes replace the actual token** | [test_reliability_resolvers.py](../tests/test_reliability_resolvers.py): `test_flag_subjects_match_actual_argument_tokens`, `test_help_does_not_verify_punctuation_prefix`, `test_hash_comments_follow_shell_word_boundaries` | Keep punctuation-bearing option names intact, including embedded `#`; omit attached values and operands after `--`. Compare exact subjects with an independent argument parser/shell oracle. |
| **F6: counts bind to the wrong truth source or lose their sign** | [test_reliability_counts.py](../tests/test_reliability_counts.py): `test_equivalent_count_layouts_bind_to_the_same_sources`, `test_equal_values_cannot_hide_an_incorrect_label_first_count`, signed-count cases | Handle number-first prose, label-first lines, and label/value table rows without borrowing another count's source. Preserve signs, source identities, and order independence. Unclear binding is unknown. |
| **F7: manifest-relative executables follow caller cwd** | [test_reliability_cli.py](../tests/test_reliability_cli.py): `test_manifest_command_authority_is_independent_of_cwd`, `test_manifest_configures_probe_limits_without_rewriting_aliases` | Resolve path-bearing declarations beside the manifest and retain the document alias. Changing cwd cannot change the selected executable or verdict. Bare executable names continue to use PATH. |
| **F8: local URL meaning depends on which spelling exists** | [test_reliability_markdown.py](../tests/test_reliability_markdown.py): percent encoding, query, nonlocal URL, and encoded traversal cases | Separate URL components, decode the path once, and enforce the project boundary after resolution. Literal `%` requires `%25`; external schemes and unverified fragments stay unknown. |
| **F9: displayed Markdown examples become link claims** | [test_reliability_markdown.py](../tests/test_reliability_markdown.py): code-span width, escaped markers, comments, and paragraph-boundary cases | Code/examples leave the link/count denominator while following real links keep their original locations. Wrapped code spans cannot consume later paragraphs. |
| **F10: `[rag]` misses the built-in provider dependency** | [pyproject.toml](../pyproject.toml) declares `attune-rag[claude]`; [wheel_smoke.py](../scripts/wheel_smoke.py) with `--check-rag-extra` constructs the installed adapter | Clean installation of each exact distribution with `[rag]` constructs the real judge. Block network access during factory construction and use a placeholder credential; no paid model request is required or asserted. |
| **F11: zero tested mutants reports 100%** | [test_mutation_gate.py](../tests/test_mutation_gate.py): inconclusive evidence, invalid thresholds, and threshold measurement; [mutation_gate.py](../scripts/mutation_gate.py) | Zero completed tests, invalid counts/schema, and unresolved execution failures cannot pass. Account for unfinished/non-killed outcomes without inflating the denominator's successful kills; keep the 75% threshold. |
| **F12: JSON failures depend on output destination** | [test_reliability_cli.py](../tests/test_reliability_cli.py): invalid JSON, evaluation ID validation, stdout/file equivalence, ASCII-stream and serialization cases | Reject nonfinite or excessively nested JSON as invalid input with exit 2 and a concise error. Preserve existing output files. Stdout and file reports use the same valid JSON representation. |
| **F13: malformed parsing and repeated failures consume excessive work** | [test_reliability_markdown.py](../tests/test_reliability_markdown.py): long unmatched brackets; [test_process_limits.py](../tests/test_process_limits.py): attempt, output, deadline, cache, scope, and evidence preservation cases | Avoid repeated rescanning of unmatched Markdown prefixes. Reuse failed observations within an operation; enforce aggregate subprocess limits and retain per-location unknowns after exhaustion. |
| **F14: the uploaded artifact lacks an exact test chain** | [test_release_artifacts.py](../tests/test_release_artifacts.py): tag/version, exact-commit CI, modified-byte, evidence-schema, and workflow-order cases; [release_artifacts.py](../scripts/release_artifacts.py), [wheel_smoke.py](../scripts/wheel_smoke.py), and [publish-pypi.yml](../.github/workflows/publish-pypi.yml) | Require source/ref/version agreement, successful selected-SHA CI evidence, positive and negative installed checks of the exact wheel/sdist, matching hashes before upload, and human PyPI approval. |
| **Semantic coverage and empty grounding** | [test_reliability_semantic.py](../tests/test_reliability_semantic.py) and [test_semantic_contract.py](../tests/test_semantic_contract.py) | Empty content or blank grounding remains unknown before judge invocation. A faithful verdict on nonempty content is a document-level observation; use `required_kinds` when publication also requires deterministic claim categories. |

## Assurance boundaries

A plain Python import uses `importlib.util.find_spec` to establish module
location. It does not execute that module merely to prove the initializer works;
looking up a dotted name can execute parent initializers. Named-symbol checks
load the declared module and inspect the symbol or child module. The generated
code itself is parsed, never executed. Import location, symbol resolution, and
successful execution of a complete example are different assurances.

Markdown extraction covers the supported fenced/inline code, comment, escape,
inline link, and reference link forms exercised above. It is a bounded subset of
Markdown. Raw HTML links and complete container/indented-code parsing remain
outside the supported surface. External link fetching and heading validation
remain unknown. A strict pass describes extracted supported claims, not every
factual assertion in the document.

Count binding is a local heuristic over caller-declared labels. Single-digit
values, decimals, and version components remain outside extraction. Signs are
preserved; integers longer than 1,024 digits become unknown observations so they
cannot abort other count checks. Count-source callbacks remain trusted caller
code.

Flag checking validates option names against captured or allowlisted help. It
does not validate argument values, prove command success, or execute generated
shell text. Ambiguous short-option clusters remain unknown if no supported
reading matches.

Artifact receipts are conservative local evidence. They cover the document,
interpreter, and discoverable import files represented in the receipt; they do
not cover all transitive dependencies or runtime behavior. Retain these limits
when interpreting an `unchanged` result.

## Resolver work limits

The defaults are shared across one public `verify`, receipt `capture`, or
`impact` operation:

| `VerifyContext` / JSON field | Default | Meaning |
|---|---:|---|
| `max_probe_attempts` | 64 | Distinct child attempts, including failed launches. |
| `probe_timeout_seconds` | 30.0 | Aggregate probe deadline; an individual probe also has a ten-second timeout. |
| `max_probe_output_bytes` | 1,048,576 | Combined captured stdout and stderr across children. |

A local calibration of 55 synthetic corpus cases on macOS/Python 3.12 observed
per-case maxima of three probes, 90 captured bytes, and 0.0849 seconds. This gives
the defaults headroom over those fixtures. It is a bounded synthetic measurement,
not a field benchmark, performance SLA, or substitute for final candidate checks.

Identical resolver requests reuse successes and failures within that operation.
Each document location still receives its own observation. A new public
operation starts with a fresh budget/cache. Exhaustion is unknown and leaves
finished evidence intact. These limits do not sandbox trusted child executables
or bound semantic model calls and count callbacks.

`VerifyContext.help_executables` explicitly maps an allowed document command
alias to an executable path. JSON manifests derive this mapping from path-bearing
`allowed_help_cmds`; they do not accept a separate `help_executables` field.
Captured `help_commands` take precedence. These are declared sources of truth,
not automatically discovered authority.

## Exact distribution acceptance

The release workflow must build the wheel and sdist once for the selected
version tag and source SHA. [release_artifacts.py](../scripts/release_artifacts.py)
checks distribution metadata and records their SHA-256 hashes. Installed checks
must consume those exact files, with source import paths removed. A separate
rebuilt distribution cannot stand in for them.

For each distribution, the installed smoke requires:

- Importable public API, matching installed package identity, and the console
  entry point outside the checkout.
- A verified document exiting **0**; refuted, unknown, and empty supported-claim
  documents each exiting **1** under strict policy.
- Missing/invalid input and protected output destinations exiting **2** while
  preserving protected bytes.
- Receipt capture and unchanged impact exiting **0**, with altered or unsupported
  evidence requesting recheck.
- Valid JSON reports, including invalid nonfinite/deep JSON rejection.
- Optional `[rag]` factory construction with network access blocked. Installing
  dependencies may access package indexes; the check makes no model request.

The retained packet binds the version and tag, full source SHA, wheel/sdist
filenames and hashes, installed smoke results, and successful tests/mutation
workflow identities for that same SHA. Preserve the raw mutation statistics and
relevant supported-runtime logs alongside it. Revalidate artifact hashes and
smoke evidence after downloading them into the publish job; do not rebuild there.

The configured test matrix includes Linux on Python 3.10–3.13 and macOS/Windows on
Python 3.12. The final candidate needs the required remote matrix and mutation
runs; a successful local macOS run does not establish Linux or Windows behavior.
Corpus precision/recall and mutation gates apply to their configured scopes and
must not be presented as representative field accuracy.

The Linux mutation workflow runs four workers and stops a mutant worker whose
observed resident memory exceeds 1 GiB. The runner validates process ownership
before signalling through a pidfd. A resource stop counts as a timeout, never a
killed mutant; forced termination fails the run. This polled limit bounds runaway
workers but is not a hard memory reservation. The runner records worker identity,
elapsed time, CPU, memory, and resource-stop events. It disables ordinary core
files and records the kernel core-dump configuration; a host pipe handler can
override that suppression.

The mutation step has a 40-minute deadline inside the 45-minute job, leaving time
for unconditional export and upload of partial metadata and diagnostics. An
interrupted or incomplete run cannot satisfy release acceptance. A host failure
can still prevent upload; missing evidence never establishes success.

Publication retains the `pypi` environment reference. The initial live audit on
2026-09-10 found no reviewer protection. With owner authorization, the environment
was updated and verified to require `silversurfer562` as its human reviewer.
Confirm that protection before each release. The final approval remains the
reviewer's own action in GitHub Actions; the agent must not approve it through
the API. A prepared packet, tag, or successful build does not imply publication.

## Completion rule

All original P1 counterexamples need desired-behavior regressions, and each P2
item needs repaired behavior or an explicit scoped limitation. Adding malformed
independent content must not remove a known refutation. Claim source, subject,
status, and location assertions matter alongside overall success. Complete the
local and remote validation packet for the exact release bytes before publication
and satisfy the required human approval gate after its authorized configuration.
