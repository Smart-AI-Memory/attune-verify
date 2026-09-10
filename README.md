# attune-verify

Generation fact-checker for the attune-\* family. Verifies named entities
in LLM-generated content actually exist — imports import, CLI flags are real,
links resolve, counts match source — so hallucinations that pass unit tests
are caught before they reach a reader.

## Install

```bash
pip install attune-verify
```

With the optional LLM semantic layer (requires attune-rag):

```bash
pip install 'attune-verify[rag]'
```

## Quick start

```python
from attune_verify import verify, VerifyContext
from pathlib import Path

ctx = VerifyContext(
    project_root=Path("."),
    allowed_help_cmds=frozenset(["attune"]),
)
result = verify(generated_content, ctx)
if not result.ok:
    for f in result.findings:
        print(f"{f.kind}: {f.detail}")
```

## Part of the attune family

- **attune-rag** grounds generation in accurate retrieved sources (input-side)
- **attune-verify** checks that named entities in the output actually exist (output-side)

Together they bracket generation: rag verifies *"is this claim supported?"*;
verify checks *"does this named thing exist?"*

## What each checker verifies

| Checker | Claim it settles | Truth source you declare |
|---|---|---|
| imports | absolute modules and named imported symbols resolve; explicit Python syntax parses | `env_python` |
| flags | every `--flag` in an inline span or shell fence appears in that command's `--help` | `help_commands` / `allowed_help_cmds` |
| links | every local markdown link target exists under the project | `project_root` |
| counts | supported numeric claims match an unambiguous declared count source | `count_sources` |

Findings are `error` when a claim is refuted; checker failures produce warnings.
Unverifiable supported claims are recorded as unknown observations. `result.ok` is False
only on errors; `raise_if_failed(result)` turns it into a hard gate.

## Status

Beta — the deterministic core (imports, flags, links, counts) is guarded by a labeled precision/recall corpus (gated ≥ 0.95 each) and mutation
testing (gated ≥ 0.75). The public API above (`verify`, `VerifyContext`,
`VerifyResult`, `Finding`, `FindingKind`, `raise_if_failed`, and the `Judge`
protocol) is what beta covers: it will not change shape without a deprecation
in a minor release. The LLM semantic layer is optional via the `[rag]` extra
and is the least settled part of the surface.

Links are read from prose only. Inline (`[text](target)`) and all three
reference forms — full `[text][label]`, collapsed `[text][]`, and shortcut
`[text]` — resolve against the document's `[label]: target` definitions. An
explicit reference whose label is never defined is an error: it renders as
literal text, so the link does not exist. An *undefined shortcut* is ordinary
prose (`the [3] case` is not a broken link) and is skipped, as are GFM
footnotes, which share the same syntax.

Both `--long` and `-short` flags are checked. A single-letter short flag is
unambiguous, so an absent one is an error. A longer single-dash token is not:
`-xzf` may be a cluster of three flags, `-name` a single-dash long option, and
`-j4` a flag with an attached value. Each reading is tried, and if none
verifies the finding is a **warning** rather than an error — an ambiguous token
is unverifiable, not refuted.

### Known limitations

- A dash followed by digits (`-5`) is read as a negative number, not a flag,
  so a numeric short flag (`head -5`) is not checked.
- A flag written as bare `` `--flag` `` in prose is attributed to the nearest
  preceding word, so it may degrade to a warning rather than resolve.
- Counts currently extract integers with two or more digits (including grouped
  thousands), outside code. Single digits, decimals and version components are
  outside that extractor. Matching uses nearby source keywords without crossing
  another number; ambiguous or unbound supported counts are unknown.
- External URLs and fragment targets are unknown: no network or heading checks
  are performed. Relative and wildcard Python imports are also unknown.

## License

Apache 2.0

## Publication policy and claim coverage

`result.ok` remains the backward-compatible “no error findings” result. It
**does not mean every statement was checked**. Use `result.passes()` for the
strict policy: at least one supported claim, no refuted or unknown claims,
and no checker warnings. `VerificationPolicy(required_kinds=("imports",))`
can additionally require a checker category. `raise_if_failed(result,
policy=VerificationPolicy())` applies that policy; omitting policy preserves
legacy behavior.

`result.claims` records verified/refuted/unknown observations with document
locations, evidence text, and source identifiers. `result.coverage` counts
those observations; `result.to_dict()` provides versioned JSON. This is a
**supported-claim denominator**, not coverage of all factual prose. A positive
import result proves resolution in the declared interpreter, not that the
surrounding example executes correctly. Unknown observations may exist without
legacy warning findings.

## CLI and explicit context

```bash
attune-verify check examples/verified.md --context examples/verify.json
attune-verify check examples/verified.md --format json --output report.json
```

Exit codes: **0** accepted, **1** rejected, **2** invalid input/configuration.
The CLI defaults to strict policy; `--policy errors` selects legacy behavior.
Report outputs must stay under the calling directory, cannot be symlinks or
repository metadata, and cannot overwrite command inputs. Parent directories
must already exist. Inputs are regular UTF-8 files, limited to 4 MiB each.

A JSON context declares `schema_version: 1`, `project_root`, optional
`env_python`, captured `help_commands`, optional `allowed_help_cmds`, and
`count_sources`. Counts are integers or `{ "glob": "relative/pattern" }`;
globs count unique regular files afresh. Paths in the context resolve against
the manifest directory. Document links resolve against each document's directory
within the project root. See `examples/verify.json`.

**Trust boundary:** the context is trusted executable configuration. Import
checks and receipt capture may execute installed package initializers;
allowlisted help commands execute with `--help`. Child processes have a timeout
but are not sandboxes. Generated code fences themselves are parsed, never run.
Use a disposable, restricted environment for untrusted packages. Captured help
text avoids executing commands. The CLI never invokes a semantic model.

### Pre-commit and CI

The repository exposes the `attune-verify` pre-commit hook (Python environment,
Markdown files). Pin the revision containing this feature when configuring a
consumer; add `args: [--context, verify.json]`. Install any packages whose imports
are being checked with the hook's `additional_dependencies`, or declare the
intended interpreter explicitly. The hook environment is otherwise isolated.

In CI, install the package and the target artifact, then run:

```bash
attune-verify check docs/api.md --context verify.json --format json --output verification.json
```

Archive the JSON report even when the gate rejects the document. This repository's
CI also builds a wheel and checks its installed CLI outside the source checkout.

## Python API evidence pilot

```bash
attune-verify receipts examples/verified.md --output receipts.json
attune-verify impact receipts.json
```

Receipts connect import claim IDs and document lines to a document hash,
interpreter identity/version, and file hashes for the imported module, parent
initializers, and discoverable defining module. `impact` resolves artifacts
again in the declared environment. It never opens artifact paths taken from the
saved JSON. Run it with a context pointing at an installed-wheel interpreter to
compare the installed artifact with the original checkout evidence.

An altered document is `document-changed`; altered artifacts or interpreter are
`recheck`; missing/unresolvable or unsupported evidence is `unknown`. Only
`unchanged` observations produce exit 0. Paths are part of fingerprints, so a
relocated installation conservatively requests rechecking. Built-ins without
files and documents without import evidence remain unknown. This pilot does
not capture all transitive dependencies, dynamic exports, package resources or
runtime behavior. It does not infer API breakage or regenerate documentation.
Receipts are unsigned local evidence, not tamper-proof attestations.

## Evaluation and human review

```bash
attune-verify evaluate evaluation/real_documents.json --output metrics.json
```

This command measures **document-level error detection**, reporting precision,
recall, unknown observations, document abstention, and elapsed time. Undefined
ratios are JSON null. It is an evaluator, not an accuracy gate: exit 0 means the
corpus was processed, not that an accuracy threshold passed.

The seed packet contains a provenance-bearing README excerpt, a deliberately
corrupted derivative, and an unlabeled held-out prose excerpt. It is a harness
seed, not a representative field benchmark. Machine labels are separate from
human held-out labels; `human_validated_metrics` is null until an independent
reviewer supplies labels. Follow `evaluation/README.md` before publishing an
accuracy claim. The existing synthetic regression corpus remains a separate CI
gate; passing it is not evidence of real-world accuracy.
