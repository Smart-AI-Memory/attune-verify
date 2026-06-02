"""Import checker — verifies Python imports in code fences resolve."""
from __future__ import annotations

import ast
import importlib.util
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

    Args:
        fences: Code fences extracted from generated content.
        env_python: Python interpreter to resolve imports against.

    Returns:
        List of findings for unresolvable imports.
    """
    findings: List[Finding] = []
    for fence in fences:
        if fence.language not in ("python", "py", ""):
            continue
        try:
            tree = ast.parse(fence.content)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            module = _module_from_node(node)
            if module and not _resolves(module, env_python):
                findings.append(Finding(
                    kind=FindingKind.UNRESOLVED_IMPORT,
                    detail=f"Import '{module}' does not resolve in {env_python}",
                    evidence=f"import {module}",
                    location=f"line {fence.line}" if fence.line else None,
                    severity="error",
                ))
    return findings


def _module_from_node(node: ast.AST) -> str | None:
    if isinstance(node, ast.Import):
        return node.names[0].name.split(".")[0] if node.names else None
    if isinstance(node, ast.ImportFrom) and node.module:
        return node.module.split(".")[0]
    return None


def _resolves(module: str, env_python: str) -> bool:
    """Return True if module is importable in env_python."""
    result = subprocess.run(
        [env_python, "-c", f"import importlib.util; "
         f"print(importlib.util.find_spec('{module}') is not None)"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
    )
    return result.stdout.strip() == "True"
