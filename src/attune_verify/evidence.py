"""Conservative Python import receipts, not a dependency graph or sandbox."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from attune_verify import VerifyContext
from attune_verify._extract import extract_code_fences
from attune_verify.checkers.imports import check_imports
from attune_verify.claims import Claim
from attune_verify.files import contained, read_text

_FINGERPRINT = """
import hashlib, importlib, inspect, json, pathlib, sys
module, symbol = sys.argv[1:3]
try:
    loaded = importlib.import_module(module)
    obj = loaded
    if symbol:
        try:
            obj = getattr(loaded, symbol)
        except AttributeError:
            obj = importlib.import_module(module + '.' + symbol)
    paths = set()
    for candidate in (loaded, inspect.getmodule(obj)):
        origin = getattr(candidate, '__file__', None)
        if origin:
            paths.add(str(pathlib.Path(origin).resolve()))
    for i in range(1, len(module.split('.'))):
        parent = sys.modules.get('.'.join(module.split('.')[:i]))
        origin = getattr(parent, '__file__', None)
        if origin:
            paths.add(str(pathlib.Path(origin).resolve()))
    artifacts = {p: hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest() for p in paths}
    result = {'artifacts': artifacts, 'python': sys.version, 'executable': sys.executable}
    if not artifacts:
        result['error'] = 'No file-backed artifact (native, frozen or namespace module)'
except Exception as exc:
    result = {'error': type(exc).__name__ + ': ' + str(exc)}
print('ATTUNE_EVIDENCE:' + json.dumps(result))
"""


def fingerprint(subject: str, env_python: str) -> dict:
    """Resolve fresh artifact paths in a declared trusted interpreter."""
    module, _, symbol = subject.partition(":")
    if not all(part.isidentifier() for part in module.split(".")) or (
        symbol and not symbol.isidentifier()
    ):
        return {"error": "Unsupported Python import subject"}
    try:
        process = subprocess.run(
            [env_python, "-c", _FINGERPRINT, module, symbol],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
        )
        lines = [
            line for line in process.stdout.splitlines() if line.startswith("ATTUNE_EVIDENCE:")
        ]
        if process.returncode or not lines:
            return {"error": "Artifact probe failed"}
        result = json.loads(lines[-1].partition(":")[2])
        if not isinstance(result, dict):
            return {"error": "Invalid artifact probe response"}
        return result
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return {"error": str(exc)}


def capture(files: list[Path], context: VerifyContext) -> dict:
    """Capture supported import locations and fingerprints for later rechecks."""
    root = Path(context.project_root).resolve()
    documents = []
    for filename in files:
        path = contained(filename.resolve(), root)
        content = read_text(path)
        observations: list[Claim] = []
        check_imports(extract_code_fences(content), context.env_python, claims=observations)
        claims = []
        for claim in observations:
            if claim.kind != "imports":
                continue
            artifact = (
                fingerprint(claim.subject, context.env_python)
                if claim.status == "verified"
                else {"error": claim.detail}
            )
            claims.append(
                {
                    "id": claim.id,
                    "subject": claim.subject,
                    "location": claim.location,
                    "fingerprint": artifact,
                }
            )
        documents.append(
            {
                "file": str(path.relative_to(root)),
                "sha256": hashlib.sha256(content.encode()).hexdigest(),
                "claims": claims,
            }
        )
    return {"schema_version": 1, "scope": "python-import-artifacts", "documents": documents}


def impact(receipt: dict, context: VerifyContext) -> dict:
    """Report recheck locations; saved artifact paths are never opened."""
    if (
        not isinstance(receipt, dict)
        or receipt.get("schema_version") != 1
        or receipt.get("scope") != "python-import-artifacts"
        or not isinstance(receipt.get("documents"), list)
    ):
        raise ValueError("Invalid Python evidence receipt")
    observations = []
    for document in receipt["documents"]:
        if not isinstance(document, dict) or not isinstance(document.get("file"), str):
            raise ValueError("Invalid receipt document")
        path = contained(Path(context.project_root) / document["file"], context.project_root)
        try:
            if not path.exists():
                raise FileNotFoundError(path)
            stale = hashlib.sha256(read_text(path).encode()).hexdigest() != document.get("sha256")
        except FileNotFoundError:
            stale = True
        claims = document.get("claims")
        if not isinstance(claims, list):
            raise ValueError("Invalid receipt claims")
        for claim in claims:
            if not isinstance(claim, dict) or not isinstance(claim.get("subject"), str):
                raise ValueError("Invalid receipt claim")
            previous = claim.get("fingerprint")
            if not isinstance(previous, dict):
                raise ValueError("Invalid saved fingerprint")
            current = fingerprint(claim["subject"], context.env_python)
            status = (
                "document-changed"
                if stale
                else (
                    "unknown"
                    if "error" in current or "error" in previous
                    else "unchanged" if current == previous else "recheck"
                )
            )
            observations.append(
                {
                    "file": document["file"],
                    "location": claim.get("location"),
                    "subject": claim["subject"],
                    "status": status,
                    "detail": current.get("error", ""),
                }
            )
        if not claims:
            observations.append(
                {
                    "file": document["file"],
                    "location": None,
                    "subject": None,
                    "status": "unknown",
                    "detail": "No Python import receipts",
                }
            )
    return {
        "schema_version": 1,
        "observations": observations,
        "needs_recheck": not observations or any(o["status"] != "unchanged" for o in observations),
    }
