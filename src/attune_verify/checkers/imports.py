"""Import checker — verifies Python imports in code fences resolve."""

from __future__ import annotations

import ast
import subprocess
import sys
from typing import List

from attune_verify._extract import CodeFence
from attune_verify.result import Finding, FindingKind


def check_imports(
    fences: List[CodeFence],
    env_python: str = sys.executable,
) -> List[Finding]:
    """Resolve every import in Python code fences against env_python.

    Each import is resolved by its FULL dotted module path, so a private
    submodule of an installed package (``from pkg.fake_sub import X``) is
    flagged — not just a fully-unknown top-level package.

    Args:
        fences: Code fences extracted from generated content.
        env_python: Python interpreter to resolve imports against.

    Returns:
        List of findings for unresolvable imports.
    """
    findings: List[Finding] = []
    # Each resolution is a subprocess; repeated imports of the same module
    # across fences are common, so resolve each module once per call.
    resolution_cache: dict[str, bool] = {}
    for fence in fences:
        # "" is a bare fence: LLM output routinely omits the language tag, so
        # parse speculatively — non-Python content fails ast.parse and is skipped.
        if fence.language not in ("python", "py", ""):
            continue
        try:
            tree = ast.parse(fence.content)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            for module in _modules_from_node(node):
                location = f"line {fence.line}" if fence.line else None
                try:
                    if module in resolution_cache:
                        resolved = resolution_cache[module]
                    else:
                        resolved = _resolves(module, env_python)
                        resolution_cache[module] = resolved
                except (OSError, subprocess.TimeoutExpired) as exc:
                    # Resolution infrastructure failed (bad env_python, timeout).
                    # Degrade per-import — the remaining imports must still run.
                    findings.append(
                        Finding(
                            kind=FindingKind.UNRESOLVED_IMPORT,
                            detail=(
                                f"Import '{module}' could not be verified "
                                f"({type(exc).__name__}: {exc})"
                            ),
                            evidence=f"import {module}",
                            location=location,
                            severity="warning",
                        )
                    )
                    continue
                if not resolved:
                    findings.append(
                        Finding(
                            kind=FindingKind.UNRESOLVED_IMPORT,
                            detail=f"Import '{module}' does not resolve in {env_python}",
                            evidence=f"import {module}",
                            location=location,
                            severity="error",
                        )
                    )
    return findings


def _modules_from_node(node: ast.AST) -> list[str]:
    """Return every FULL dotted module path imported by an import node.

    ``find_spec`` resolves submodules (e.g. ``attune.ops._readers``), so
    returning the full path — not just the top-level package — catches a
    private submodule of an *installed* package that does not actually
    exist. Returning only ``attune`` would let ``from attune.ops._readers
    import X`` pass when ``attune`` is installed (the v0.1.0 gap).

    A single statement may import several modules (``import a, b, c``); each
    is returned so a fake name hiding behind a real one is still flagged.
    Relative imports (``from . import x``, ``from .pkg import y``) cannot be
    resolved outside their package context and are skipped — flagging them
    would be a false positive.
    """
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        if node.level and node.level > 0:  # relative import — unresolvable here
            return []
        if node.module:
            return [node.module]
    return []


def _resolves(module: str, env_python: str) -> bool:
    """Return True if module is importable in env_python."""
    result = subprocess.run(
        [
            env_python,
            "-c",
            f"import importlib.util; " f"print(importlib.util.find_spec('{module}') is not None)",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
    )
    return result.stdout.strip() == "True"
