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
| imports | every import in a Python code fence resolves, by full dotted path | `env_python` |
| flags | every `--flag` in an inline span or shell fence appears in that command's `--help` | `help_commands` / `allowed_help_cmds` |
| links | every local markdown link target exists under the project | `project_root` |
| counts | every numeric claim matches the number it names | `count_sources` |

Findings are `error` when a claim is refuted and `warning` when it cannot be
checked — an unverifiable claim is never a silent pass. `result.ok` is False
only on errors; `raise_if_failed(result)` turns it into a hard gate.

## Status

Beta — the deterministic core (imports, flags, links, counts) is stable and
guarded by a labeled precision/recall corpus (gated ≥ 0.95 each) and mutation
testing (gated ≥ 0.75). The public API above (`verify`, `VerifyContext`,
`VerifyResult`, `Finding`, `FindingKind`, `raise_if_failed`, and the `Judge`
protocol) is what beta covers: it will not change shape without a deprecation
in a minor release. The LLM semantic layer is optional via the `[rag]` extra
and is the least settled part of the surface.

### Known limitations

- Reference-style links (`[text][ref]`) are not resolved — only inline
  `[text](target)` links are checked.
- Short flags (`-v`) are not checked; only `--long` forms are.
- A flag written as bare `` `--flag` `` in prose is attributed to the nearest
  preceding word, so it may degrade to a warning rather than resolve.
- Counts are matched to a source by keyword overlap with the claim's
  surrounding text; a numeric claim whose context names no source is skipped
  rather than guessed at.

## License

Apache 2.0
