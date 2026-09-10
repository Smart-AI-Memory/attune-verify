# attune-verify

Generation fact-checker for the attune-\* family. Checks Python module locations,
named imports, CLI options, project links, and supported numeric claims against
the truth sources you declare. The deterministic core has no runtime dependencies.

## Install

```bash
pip install attune-verify
```

With the optional LLM semantic layer and its built-in provider dependencies:

```bash
pip install 'attune-verify[rag]'
```

The extra installs `attune-rag[claude]`. Live semantic verification still requires
appropriate provider authentication. Release checks construct the real adapter
with network access blocked; they do not make paid model calls.

## Quick start

```python
from attune_verify import verify, VerifyContext
from pathlib import Path

ctx = VerifyContext(
    project_root=Path("."),
    allowed_help_cmds=frozenset(["attune"]),
)
result = verify(generated_content, ctx)
if not result.passes():
    print(result.to_dict())  # includes refuted and unknown observations
```

## Part of the attune family

- **attune-rag** grounds generation in accurate retrieved sources (input-side)
- **attune-verify** checks that named entities in the output actually exist (output-side)

Together they bracket generation: rag verifies *"is this claim supported?"*;
verify checks *"does this named thing exist?"*

## What each checker verifies

| Checker | Claim it settles | Truth source you declare |
|---|---|---|
| imports | plain imports have an import-system location; named symbols resolve after loading their module; explicit Python syntax parses | `env_python` |
| flags | supported option tokens in command spans or shell fences match that command's `--help` | `help_commands` / `allowed_help_cmds` |
| links | extracted local Markdown destinations exist under the project | `project_root` |
| counts | supported numeric claims match an unambiguous declared count source | `count_sources` |

Findings are `error` when a claim is refuted; checker failures produce warnings.
Unverifiable supported claims are recorded as unknown observations. `result.ok` is
False only on errors; the default `raise_if_failed(result)` enforces that legacy
policy. Use `result.passes()` or pass `VerificationPolicy()` to `raise_if_failed`
for the strict publication policy described below. A failed provider or malformed
claim preserves independently completed findings and observations.

## Status

Beta — CI is configured to gate a labeled precision/recall corpus at ≥ 0.95 each
and mutation testing at ≥ 0.75. Empty or incomplete mutation evidence cannot
satisfy the gate. These thresholds describe the checked corpus and mutation
configuration; they are not a field-accuracy guarantee. The public API (`verify`, `VerifyContext`,
`VerifyResult`, `Finding`, `FindingKind`, `raise_if_failed`, and the `Judge`
protocol) is what beta covers: it will not change shape without a deprecation
in a minor release. The LLM semantic layer is optional via the `[rag]` extra
and is the least settled part of the surface.

The Markdown scanner excludes fenced code, inline code spans, HTML comments,
and escaped link markers from link/count extraction. Inline spans can use longer
backtick delimiters and wrap within a paragraph. An unclosed backtick or tilde
fence extends to EOF, so truncation cannot silently remove its Python claims.

Inline links (`[text](target)`) and all three
reference forms — full `[text][label]`, collapsed `[text][]`, and shortcut
`[text]` — resolve against the document's `[label]: target` definitions. An
explicit reference whose label is never defined is an error: it renders as
literal text, so the link does not exist. An *undefined shortcut* is ordinary
prose (`the [3] case` is not a broken link) and is skipped, as are GFM
footnotes, which share the same syntax.

Nested brackets in link text and balanced parentheses in destinations are
supported. Local URL queries are separated from the filesystem path, and the path
is percent-decoded once. For a file literally named `a%20b.md`, write
`a%2520b.md`; `a%20b.md` refers to `a b.md`. Relative destinations use the document
directory when `document_path` is supplied; `/docs/page.md` uses the project root.
Resolved paths outside the project are unknown. External schemes, including
uppercase HTTP(S), and fragment checks remain unknown.

Both `--long` and `-short` flags are checked. A single-letter short flag is
unambiguous, so an absent one is an error. A longer single-dash token is not:
`-xzf` may be a cluster of three flags, `-name` a single-dash long option, and
`-j4` a flag with an attached value. Each reading is tried, and if none
verifies the finding is a **warning** rather than an error — an ambiguous token
is unverifiable, not refuted.

Option matching preserves the whole token: `--verbose.extra` cannot verify as
`--verbose`. An attached `=value` is excluded from the option name, and operands
after `--` are excluded from flag claims. A `#` inside an option is retained;
an unquoted comment beginning at a shell word boundary is ignored. The checker
compares option names with help text; it does not validate argument values or
execute the generated command.

### Known limitations

- A dash followed by digits (`-5`) is read as a negative number, not a flag,
  so a numeric short flag (`head -5`) is not checked.
- A flag written as bare `` `--flag` `` in prose is attributed to the nearest
  preceding word, so it may degrade to a warning rather than resolve.
- Counts currently extract integers with two or more digits (including grouped
  thousands), preserving a leading sign. Single digits, decimals and version
  components are outside that extractor. Matching compares nearby source labels
  on both sides within clause, line, and table boundaries; ambiguous or unbound
  supported counts are unknown. Integers longer than 1,024 digits are unknown
  without preventing neighboring counts from being checked.
- External URLs and fragment targets are unknown: no network or heading checks
  are performed. Relative and wildcard Python imports are also unknown.
- Markdown support is a bounded subset, not a complete CommonMark/GFM renderer.
  Raw HTML links and full container/indented-code parsing are outside its scope.

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

A plain `import package` uses `importlib.util.find_spec`: it establishes that the
import system can locate the module. It does not establish that the module's
initializer will execute successfully. Looking up a dotted module can execute
parent initializers. `from package import symbol` loads the module to check the
symbol or an importable child module. Generated examples themselves are never run.

The optional semantic verdict is a document-level observation. Empty content and
blank grounding remain unknown, and the judge is not invoked for either. For
nonempty content with usable grounding, a faithful verdict can satisfy the default
supported-claim requirement; use `required_kinds` to require deterministic
categories as well.

## CLI and explicit context

```bash
attune-verify check examples/verified.md --context examples/verify.json
attune-verify check examples/verified.md --format json --output report.json
```

Exit codes: **0** accepted, **1** rejected, **2** invalid input/configuration.
The CLI defaults to strict policy; `--policy errors` selects legacy behavior.
Report outputs must stay under the calling directory, cannot be symlinks or
repository metadata, and cannot overwrite command inputs. Parent directories
must already exist. Existing filesystem aliases, including case aliases on a
case-insensitive filesystem, cannot bypass input protection. Inputs are regular
UTF-8 files, limited to 4 MiB each. JSON rejects nonfinite values and excessive
nesting as invalid input. JSON written to stdout and to a report file follows the
same serialization rules; invalid input exits 2 without emitting a success report.

A JSON context declares `schema_version: 1`, `project_root`, optional
`env_python`, captured `help_commands`, optional `allowed_help_cmds`, and
`count_sources`. Counts are integers or `{ "glob": "relative/pattern" }`;
globs count unique regular files afresh. Paths in the context resolve against
the manifest directory. Document links resolve against each document's directory
within the project root. See `examples/verify.json`.

Path-bearing `allowed_help_cmds` and `env_python` declarations resolve beside the
manifest; the command spelling in the document remains the lookup alias. Bare
executable names use PATH. The Python API can make that mapping explicit:

```python
ctx = VerifyContext(
    project_root=Path("."),
    allowed_help_cmds=frozenset({"mytool"}),
    help_executables={"mytool": str(Path("tools/mytool").resolve())},
    max_probe_attempts=64,
    probe_timeout_seconds=30.0,
    max_probe_output_bytes=1_048_576,
)
```

The three limit fields are also accepted in a JSON context. `help_executables`
is a Python API field; JSON manifests derive it from path-bearing allowlist
entries. Captured `help_commands` take precedence over executable lookup.

Each verification operation, receipt capture, or impact check shares aggregate
subprocess limits: **64 attempts, a 30-second deadline, and 1 MiB of captured
stdout/stderr**, with a ten-second cap on an individual probe. Repeated successful
or failed lookups reuse their observation within that operation while retaining
every claim location. New operations receive fresh budgets and caches. Exhaustion
produces unknown observations and preserves completed evidence. These are
subprocess limits; they do not bound semantic model calls or caller-supplied count
callbacks.

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
CI also checks installed distributions outside the source checkout. The
[maintenance reliability contract](docs/reliability.md) maps regressions to release
acceptance and explains the exact wheel/sdist evidence required before publication.

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
