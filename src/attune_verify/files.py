"""Bounded file input and atomic, project-contained report output."""

from __future__ import annotations

import json
import math
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


def _reject_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON number: {value}")


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"Non-finite JSON number: {value}")
    return number


def read_json(path: Path) -> object:
    """Read bounded JSON, rejecting non-finite numbers and excessive nesting."""
    try:
        return json.loads(
            read_text(path), parse_constant=_reject_constant, parse_float=_finite_float
        )
    except RecursionError as exc:
        raise ValueError(f"JSON nesting exceeds parser limits: {path}") from exc
    except ValueError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc


def json_text(value: object) -> str:
    """Serialize reports consistently, including on non-UTF-8 output streams."""
    try:
        return json.dumps(value, indent=2, ensure_ascii=True, allow_nan=False)
    except RecursionError as exc:
        raise ValueError("JSON nesting exceeds serializer limits") from exc


def same_file(path: Path, other: Path) -> bool:
    """Compare both prospective paths and existing filesystem identities."""
    return path.resolve() == other.resolve() or (
        path.exists() and other.exists() and path.samefile(other)
    )


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
    if any(
        part.casefold() in {".git", ".hg", ".svn"}
        for part in target.relative_to(root.resolve()).parts
    ):
        raise ValueError("Report output cannot overwrite repository metadata")
    if target.exists() and not target.is_file():
        raise ValueError(f"Output is not a regular file: {path}")
    # Require the output directory to exist: no implicit project restructuring.
    payload = json_text(value) + "\n"
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
