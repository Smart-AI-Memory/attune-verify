"""VerifyContext — declared truth boundaries for attune-verify.

The caller declares WHERE truth comes from; verify performs the lookups.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, FrozenSet, Optional, Union


@dataclass
class VerifyContext:
    """Declared boundaries for a verification run.

    verify() auto-resolves lookups *within* these boundaries.
    The caller must supply the boundaries — verify never auto-discovers them.

    Attributes:
        project_root: Root path for markdown link resolution.
        env_python: Python interpreter to use for import checks.
            Defaults to the current interpreter (sys.executable).
        help_commands: Pre-captured --help output keyed by command name.
            If a command is in this dict, its cached output is used.
        allowed_help_cmds: Commands safe to invoke --help on at runtime.
            verify will only shell out to --help for commands in this set.
            A flag referencing a command not pre-captured and not in this
            set yields a warning, not an error — never a silent pass.
        count_sources: Numeric claims to verify, keyed by label/description.
            Values may be plain ints or zero-argument callables returning int.
        judge: Optional semantic judge implementing the Judge protocol.
            Required for the semantic layer; when absent and semantic=True,
            verify degrades gracefully (warning, not error).
        semantic: Enable the LLM semantic layer. Requires a judge.
    """

    project_root: Optional[Path] = None
    env_python: str = field(default_factory=lambda: sys.executable)
    help_commands: Dict[str, str] = field(default_factory=dict)
    allowed_help_cmds: FrozenSet[str] = field(default_factory=frozenset)
    count_sources: Dict[str, Union[int, Callable[[], int]]] = field(
        default_factory=dict
    )
    judge: object = None  # Judge protocol instance
    semantic: bool = False
