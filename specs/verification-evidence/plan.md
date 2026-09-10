# Verification coverage and evidence implementation

Status: implementation complete; final verification recorded in `implementation.md`. Base: 3b9191651ebbd7030d93cd14db009d9cb38f14c8.

## Goal and scope

Make attune-verify's evidence and limits explicit, fix demonstrated false
results, and deliver a usable publication gate with a bounded Python API
change-impact pilot. Preserve the zero-dependency core and existing
verify(content, context), findings, checked and ok semantics. No paid model
calls, releases or changes to another session's checkout.

This is a spec-sized implementation in an isolated worktree. Changes remain
reviewable for the owning repository session; no automatic release or merge.

## Sequence and acceptance

1. Accuracy: imported symbols and aliases resolve, explicit malformed Python
   is reported, correct multi-count sentences do not depend on dictionary
   order, negative semantic verdicts cannot disappear, command arguments do
   not become command names. Executable regressions must fail before repair.
2. Coverage contract: identify supported claims as verified/refuted/unknown;
   report skipped supported claims and checker failures; a strict policy
   rejects unknowns and empty verification. Legacy ok retains its behavior.
   Never claim the denominator represents every natural-language assertion.
3. Adoption: stdlib JSON context manifests, CLI with human/JSON output and
   meaningful exit codes, pre-commit hook and reusable CI example. CLI works
   from an installed wheel outside the checkout. Context paths resolve against
   the manifest; output writes validate paths and reject unsafe targets.
4. Evaluation: a provenance-bearing real-document corpus and evaluation
   harness reporting precision, recall, abstention and timing. Separate
   machine-derived fixtures from human-reviewed held-out examples. Report
   absent human labels as unavailable, never as successful validation.
5. Evidence map pilot: record Python import claims, environment and artifact
   fingerprints. Given saved receipts, report affected document locations
   after source changes or removal. Recheck against an installed artifact as
   well as a checkout. Non-Python general evidence graphs and automatic
   regeneration remain outside this pilot.

## Verification

- Regression + boundary/security tests, complete existing suite, lint/format.
- Real child-interpreter import, CLI subprocess, source change/removal and
  wheel installation round trips. Semantic behavior uses owned fake judges.
- Corpus gates and mutation testing; distinguish new measurements from old CI.
- Inspect compatibility against attune-ai's taught verify/VerifyContext API.

## Human follow-up

An independent human must adjudicate the held-out real-document labels before
we publish field accuracy claims. Implementation supplies the review packet
and evaluator but cannot substitute its own labels for that receipt.

## Implemented surfaces

- Phase 1: regression fixes in imports, flags, counts and semantic orchestration.
- Phase 2: `Claim`, `ClaimStatus`, `VerificationPolicy`, versioned result reports.
- Phase 3: `check` CLI, manifests, pre-commit hook, installed-wheel CI smoke.
- Phase 4: `evaluate`, provenance-bearing seed/review packet, separate human metrics.
- Phase 5: `receipts` and `impact`, conservative import artifact fingerprints.

The human benchmark expansion/adjudication and CI's other operating systems
remain explicitly outstanding validation. General dependency graphs and automatic
document regeneration were excluded from the bounded implementation at planning.
