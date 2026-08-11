"""Packaging guards: version single-sourcing and the typing marker.

The release flow bumps two version sites by hand (``pyproject.toml`` and
``__init__.__version__``). A drift between them ships a wheel whose metadata
disagrees with the value users read at runtime, and nothing else would catch
it — so it is pinned here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import attune_verify

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PYPROJECT = _REPO_ROOT / "pyproject.toml"
_PACKAGE_ROOT = Path(attune_verify.__file__).resolve().parent


def _pyproject_field(name: str) -> str:
    text = _PYPROJECT.read_text(encoding="utf-8")
    match = re.search(rf'^{name} = "([^"]+)"', text, re.MULTILINE)
    assert match is not None, f"{name} not found in pyproject.toml"
    return match.group(1)


@pytest.mark.skipif(not _PYPROJECT.exists(), reason="running outside the source tree")
def test_version_matches_pyproject() -> None:
    assert attune_verify.__version__ == _pyproject_field("version")


@pytest.mark.skipif(not _PYPROJECT.exists(), reason="running outside the source tree")
def test_development_status_classifier_is_declared_once() -> None:
    # A stale second status classifier would misreport maturity on PyPI.
    statuses = re.findall(
        r'"Development Status :: ([^"]+)"', _PYPROJECT.read_text(encoding="utf-8")
    )
    assert len(statuses) == 1, f"expected exactly one Development Status, got {statuses}"


def test_py_typed_marker_ships_with_the_package() -> None:
    # Without the marker, PEP 561 tells type checkers to ignore the (fully
    # annotated) package entirely.
    assert (_PACKAGE_ROOT / "py.typed").is_file()


def test_public_api_is_importable_and_complete() -> None:
    for name in attune_verify.__all__:
        assert hasattr(attune_verify, name), f"__all__ names {name}, which is not exported"
