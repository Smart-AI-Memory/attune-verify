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

## Status

Alpha — the deterministic core (imports, flags, links, counts) is shipped
and guarded by a labeled precision/recall corpus (gated ≥ 0.95 each) and
mutation testing (gated ≥ 0.75). The LLM semantic layer is optional via
the `[rag]` extra.

## License

Apache 2.0
