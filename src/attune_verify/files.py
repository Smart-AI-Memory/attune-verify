"""Bounded file input and atomic, project-contained report output."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

MAX_INPUT_BYTES = 4 * 1024 * 1024


def read_text(path: Path) -> str:
    """Read a regular UTF-8 file with a bounded input size."""
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"Not a regular file: {path}")
    with path.open("rb") as stream:
        data = stream.read(MAX_INPUT_BYTES + 1)
    if len(data) > MAX_INPUT_BYTES:
        raise ValueError(f"Input exceeds {MAX_INPUT_BYTES} bytes: {path}")
    return data.decode("utf-8")


def contained(path: Path, root: Path) -> Path:
    """Resolve a declared path and refuse escape from its root."""
    root = root.resolve()
    result = (root / path).resolve()
    if not result.is_relative_to(root):
        raise ValueError(f"Path escapes declared root: {path}")
    return result


def write_json(path: Path, value: object, *, root: Path) -> None:
    """Atomically write reports under root, never to symlinks or Git metadata."""
    raw = root / path
    if raw.is_symlink():
        raise ValueError(f"Refusing symlink output: {path}")
    target = contained(path, root)
    if any(part in {".git", ".hg", ".svn"} for part in target.relative_to(root.resolve()).parts):
        raise ValueError("Report output cannot overwrite repository metadata")
    if target.exists() and not target.is_file():
        raise ValueError(f"Output is not a regular file: {path}")
    # Require the output directory to exist: no implicit project restructuring.
    payload = json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=target.parent, delete=False
        ) as stream:
            name = stream.name
            stream.write(payload)
        os.replace(name, target)
    finally:
        if name and Path(name).exists():
            Path(name).unlink()
