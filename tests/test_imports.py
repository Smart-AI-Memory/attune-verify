"""Tests for the import checker — full dotted-path resolution.

v0.2.0 resolves the *full* dotted module path, so a private submodule of
an installed package (the author-#351 ``attune.ops._readers`` class of
bug) is flagged — not just a fully-unknown top-level package. These tests
are hermetic: they use the stdlib ``os`` package, always importable, so a
fake submodule of it is a deterministic "real parent, missing child".
"""

from __future__ import annotations

from attune_verify._extract import extract_code_fences
from attune_verify.checkers.imports import check_imports
from attune_verify.result import FindingKind


def _check(src: str):
    fences = extract_code_fences(f"```python\n{src}\n```")
    return check_imports(fences)


def test_real_top_level_import_resolves() -> None:
    assert _check("import os") == []


def test_real_submodule_resolves() -> None:
    assert _check("import os.path") == []
    assert _check("from os import path") == []


def test_fully_unknown_top_level_is_flagged() -> None:
    findings = _check("import totally_fake_pkg_xyz_2026")
    assert [f.kind for f in findings] == [FindingKind.UNRESOLVED_IMPORT]


def test_fake_submodule_of_real_package_is_flagged() -> None:
    # The v0.1.0 gap: `os` is installed, but `os.totally_missing_sub` is
    # not. v0.1.0 checked only `os` (top-level) and passed; v0.2.0
    # resolves the full path and flags it.
    findings = _check("from os.totally_missing_sub import thing")
    assert [f.kind for f in findings] == [FindingKind.UNRESOLVED_IMPORT]
    assert "os.totally_missing_sub" in findings[0].detail


def test_import_fake_submodule_of_real_package_is_flagged() -> None:
    findings = _check("import os.totally_missing_sub")
    assert [f.kind for f in findings] == [FindingKind.UNRESOLVED_IMPORT]
