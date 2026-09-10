"""Opt-in temporary-directory isolation for mutmut's forked pytest workers."""

import os
from pathlib import Path

import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    root_value = os.environ.get("ATTUNE_MUTATION_TMP_ROOT")
    if root_value is None:
        return
    root = Path(root_value)
    if not root.is_absolute():
        raise pytest.UsageError("ATTUNE_MUTATION_TMP_ROOT must be an absolute dedicated directory")
    root = root.resolve()
    if root.parent == root or not root.is_dir():
        raise pytest.UsageError(
            "ATTUNE_MUTATION_TMP_ROOT must be an existing directory other than a filesystem root"
        )
    # pytest's own pytest_configure snapshots this option into TempPathFactory.
    # A fixed shared --basetemp would let concurrent workers remove each other's files.
    config.option.basetemp = str(root / f"worker-{os.getpid()}")
