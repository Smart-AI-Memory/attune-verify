# Real-document evaluation review packet

`real_documents.json` is a small seed with source commit/path provenance,
explicit transformations, and label basis. The original 55-case synthetic
corpus remains under tests/corpus; do not pool it into field accuracy claims.

To collect credible held-out evidence:

1. Sample actual generated documentation across imports, commands, counts,
   links and ordinary unsupported prose. Preserve exact content, repository,
   commit, file, intended environment and transformation (if any).
2. Choose calibration/heldout splits before tuning. Keep near-duplicate excerpts
   and corrupted derivatives in the same split to prevent leakage.
3. Have an independent human inspect each case against the declared context.
   `expected_error` means a refutable supported claim is present, not merely
   unknown or unverified prose. Record boolean `expected_error`,
   `label_basis: "human"`, `reviewer`, and `split: "heldout"` only after review.
4. Run the evaluator in the recorded environment. Inspect unknown claims and
   coverage separately: a detector that abstains on everything is not useful.
5. Report sample size and corpus composition alongside precision and recall.
   Undefined metrics stay null. The evaluator trusts supplied reviewer metadata;
   it does not authenticate a human or prevent benchmark leakage mechanically.

No human review has been performed on the supplied packet. Expanding this seed
and adjudicating labels remain human follow-up, not a completed accuracy claim.
