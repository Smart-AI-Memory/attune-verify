"""Resolve module and symbol claims in a bounded child interpreter.

Never execute the generated fence. Imports may execute trusted environment
package initializers; a child process is not a security sandbox.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys

from attune_verify._extract import CodeFence
from attune_verify._process import probe_scope, run_probe
from attune_verify.claims import Claim, record
from attune_verify.result import Finding, FindingKind

# Fixed program: untrusted identifiers travel as argv, never as Python code.
_PROBE = """
import importlib, importlib.util, json, sys
module, symbol = sys.argv[1:3]
try:
    if not symbol:
        exists = importlib.util.find_spec(module) is not None
    else:
        loaded = importlib.import_module(module)
        exists = hasattr(loaded, symbol)
        if not exists:
            importlib.import_module(module + '.' + symbol)
            exists = True
    result = {'exists': exists}
except ModuleNotFoundError as exc:
    target = module + ('.' + symbol if symbol else '')
    if exc.name and (target == exc.name or target.startswith(exc.name + '.')):
        result = {'exists': False}
    else:
        result = {'error': str(exc)}
except Exception as exc:
    result = {'error': type(exc).__name__ + ': ' + str(exc)}
print('ATTUNE_PROBE:' + json.dumps(result))
"""


def check_imports(
    fences: list[CodeFence],
    env_python: str = sys.executable,
    *,
    claims: list[Claim] | None = None,
) -> list[Finding]:
    """Check each module/symbol; report malformed explicitly tagged Python."""
    with probe_scope():
        return _check_imports(fences, env_python, claims=claims)


def _check_imports(
    fences: list[CodeFence], env_python: str, *, claims: list[Claim] | None
) -> list[Finding]:
    findings = []
    cache: dict[tuple[str, str], bool | str] = {}

    def resolves(module: str, symbol: str = "") -> bool:
        key = (module, symbol)
        if key not in cache:
            try:
                cache[key] = (
                    _probe(module, symbol, env_python) if symbol else _resolves(module, env_python)
                )
            except (OSError, subprocess.TimeoutExpired, RuntimeError, ValueError, TypeError) as exc:
                cache[key] = str(exc)
        result = cache[key]
        if isinstance(result, str):
            raise RuntimeError(result)
        return result

    for fence in fences:
        if fence.language not in ("python", "py", ""):
            continue
        try:
            tree = ast.parse(fence.content)
        except SyntaxError as exc:
            if fence.language:
                location = f"line {(fence.line or 0) + (exc.lineno or 1)}"
                finding = Finding(
                    FindingKind.INVALID_CODE, f"Invalid Python: {exc.msg}", fence.content, location
                )
                findings.append(finding)
                record(claims, "imports", "Python syntax", fence.content, location, finding)
            continue
        except (RecursionError, MemoryError) as exc:
            location = f"line {(fence.line or 0) + 1}"
            finding = Finding(
                FindingKind.INVALID_CODE,
                f"Python syntax could not be parsed ({type(exc).__name__}: {exc})",
                fence.content,
                location,
                "warning",
            )
            findings.append(finding)
            record(claims, "imports", "Python syntax", fence.content, location, finding)
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            evidence = ast.get_source_segment(fence.content, node) or ast.unparse(node)
            location = f"line {(fence.line or 0) + node.lineno}"
            if isinstance(node, ast.ImportFrom) and (
                node.level or any(alias.name == "*" for alias in node.names)
            ):
                record(
                    claims,
                    "imports",
                    evidence,
                    evidence,
                    location,
                    unknown="Relative and wildcard imports require package/export context",
                )
                continue
            for alias in node.names:
                module = alias.name if isinstance(node, ast.Import) else node.module
                symbol = "" if isinstance(node, ast.Import) else alias.name
                subject = module + (":" + symbol if symbol else "")
                finding = None
                try:
                    resolved = resolves(module)
                    if resolved and symbol:
                        resolved = resolves(module, symbol)
                    if not resolved:
                        finding = Finding(
                            FindingKind.UNRESOLVED_IMPORT,
                            f"Import '{subject}' does not resolve in {env_python}",
                            evidence,
                            location,
                        )
                except (
                    OSError,
                    subprocess.TimeoutExpired,
                    RuntimeError,
                    ValueError,
                    TypeError,
                ) as exc:
                    finding = Finding(
                        FindingKind.UNRESOLVED_IMPORT,
                        f"Import '{subject}' could not be verified ({exc})",
                        evidence,
                        location,
                        "warning",
                    )
                if finding:
                    findings.append(finding)
                record(claims, "imports", subject, evidence, location, finding, source=env_python)
    return findings


def _modules_from_node(node: ast.AST) -> list[str]:
    """Legacy internal extractor of absolute module names."""
    if isinstance(node, ast.Import):
        return [a.name for a in node.names]
    if isinstance(node, ast.ImportFrom) and node.module and not node.level:
        return [node.module]
    return []


def _resolves(module: str, env_python: str) -> bool:
    """Resolve a full module name without interpolating generated code."""
    return _probe(module, "", env_python)


def _probe(module: str, symbol: str, env_python: str) -> bool:
    """Read a framed child result, ignoring package initializer stdout."""
    result = run_probe([env_python, "-c", _PROBE, module, symbol])
    lines = [line for line in result.stdout.splitlines() if line.startswith("ATTUNE_PROBE:")]
    if result.returncode or not lines:
        raise RuntimeError("Import probe failed: " + result.stderr[-500:])
    payload = json.loads(lines[-1].partition(":")[2])
    if not isinstance(payload, dict):
        raise RuntimeError("Import probe returned an invalid result object")
    if "error" in payload:
        raise RuntimeError(str(payload["error"]))
    if type(payload.get("exists")) is not bool:
        raise RuntimeError("Import probe result must contain a boolean exists field")
    return payload["exists"]
