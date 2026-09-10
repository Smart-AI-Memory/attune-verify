"""Load explicit, versioned project truth sources; never discover authority."""

from __future__ import annotations

import json
from pathlib import Path, PureWindowsPath

from attune_verify.context import VerifyContext
from attune_verify.files import contained, read_text

_FIELDS = {
    "schema_version",
    "project_root",
    "env_python",
    "help_commands",
    "allowed_help_cmds",
    "count_sources",
}


def load_context(path: Path) -> VerifyContext:
    """Load JSON paths relative to the manifest, not the calling directory.

    A manifest is trusted configuration: interpreter and allowed help commands
    can execute installed code. Count glob sources are project-contained.
    """
    path = path.resolve()
    raw = json.loads(read_text(path))
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise ValueError("Context must be an object with schema_version: 1")
    if set(raw) - _FIELDS:
        raise ValueError(f"Unknown context fields: {sorted(set(raw) - _FIELDS)}")
    project = raw.get("project_root", ".")
    if not isinstance(project, str):
        raise ValueError("project_root must be a path string")
    root = (path.parent / project).resolve()
    if not root.is_dir():
        raise ValueError("project_root must be an existing directory")
    help_commands = raw.get("help_commands", {})
    if not isinstance(help_commands, dict) or not all(
        isinstance(k, str) and k.strip() and isinstance(v, str) for k, v in help_commands.items()
    ):
        raise ValueError("help_commands must map command names to captured help text")
    allowed = raw.get("allowed_help_cmds", [])
    if not isinstance(allowed, list) or not all(isinstance(c, str) and c for c in allowed):
        raise ValueError("allowed_help_cmds must be a list of executable names or paths")
    sources = raw.get("count_sources", {})
    if not isinstance(sources, dict):
        raise ValueError("count_sources must be an object")
    counts = {}
    for label, value in sources.items():
        if not isinstance(label, str) or not label.strip():
            raise ValueError("Count labels must be nonempty strings")
        if type(value) is int:
            counts[label] = value
        elif isinstance(value, dict) and set(value) == {"glob"}:
            pattern = value["glob"]
            if (
                not isinstance(pattern, str)
                or not pattern
                or Path(pattern).anchor
                or PureWindowsPath(pattern).anchor
                or ".." in Path(pattern).parts
                or ".." in PureWindowsPath(pattern).parts
            ):
                raise ValueError("Count globs must be relative and cannot traverse parents")
            counts[label] = _glob_counter(root, pattern)
        else:
            raise ValueError("Count sources must be integers or objects with a relative glob")
    ctx = VerifyContext(
        project_root=root,
        help_commands=help_commands,
        allowed_help_cmds=frozenset(allowed),
        count_sources=counts,
    )
    if "env_python" in raw:
        python = raw["env_python"]
        if not isinstance(python, str) or not python:
            raise ValueError("env_python must be an interpreter path or command")
        ctx.env_python = (
            str((path.parent / python).resolve()) if "/" in python or "\\" in python else python
        )
    return ctx


def _glob_counter(root: Path, pattern: str):
    """Resolve at verification time so callers cannot reuse stale counts."""

    def count() -> int:
        matches = [contained(p, root) for p in root.glob(pattern)]
        return sum(path.is_file() for path in set(matches))

    return count
