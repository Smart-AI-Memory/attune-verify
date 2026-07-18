"""Flag checker — verifies CLI flags referenced in content exist in --help."""

from __future__ import annotations

import re
import subprocess
from typing import Dict, FrozenSet, List

from attune_verify.result import Finding, FindingKind

_FLAG_RE = re.compile(r"`(--[\w-]+)`")


def check_flags(
    content: str,
    help_commands: Dict[str, str],
    allowed_help_cmds: FrozenSet[str],
) -> List[Finding]:
    """Verify flags referenced in content exist in command --help output.

    Security: only invokes --help for commands in allowed_help_cmds.
    A flag for an unknown command yields a warning, not a silent pass.

    Args:
        content: Generated content to scan for flag references.
        help_commands: Pre-captured --help text keyed by command name.
        allowed_help_cmds: Commands safe to invoke at runtime.

    Returns:
        List of findings for unverifiable or unknown flags.
    """
    findings: List[Finding] = []
    # Find patterns like "`--flag`" or "`command --flag`"
    for match in _FLAG_RE.finditer(content):
        flag = match.group(1)
        surrounding = content[max(0, match.start() - 30) : match.start()]
        cmd = _guess_command(surrounding)
        help_text = _get_help(cmd, help_commands, allowed_help_cmds)
        if help_text is None:
            findings.append(
                Finding(
                    kind=FindingKind.UNKNOWN_FLAG,
                    detail=(
                        f"Flag '{flag}' could not be verified "
                        f"(no --help output available for command '{cmd}')"
                    ),
                    evidence=match.group(0),
                    severity="warning",
                )
            )
        elif not _flag_in_help(flag, help_text):
            findings.append(
                Finding(
                    kind=FindingKind.UNKNOWN_FLAG,
                    detail=f"Flag '{flag}' not found in '{cmd} --help'",
                    evidence=match.group(0),
                    severity="error",
                )
            )
    return findings


def _flag_in_help(flag: str, help_text: str) -> bool:
    """Return True if flag appears in help as a whole token.

    A plain substring test gives false negatives: ``--ver`` would pass
    because ``--verbose`` contains it. Require the flag not be immediately
    followed by another flag character (word char or hyphen).
    """
    return re.search(re.escape(flag) + r"(?![\w-])", help_text) is not None


def _guess_command(preceding: str) -> str:
    """Heuristically extract the command name preceding a flag."""
    words = preceding.strip().split()
    for word in reversed(words):
        cleaned = word.strip("`")
        if cleaned and not cleaned.startswith("-"):
            return cleaned
    return "unknown"


def _get_help(
    cmd: str,
    help_commands: Dict[str, str],
    allowed_help_cmds: FrozenSet[str],
) -> str | None:
    """Return help text, or None if the command cannot be introspected.

    None covers three cases: the command is not allow-listed, its binary is
    missing, or --help failed to run. A failed subprocess degrades to None
    (per-flag warning) rather than raising — one broken command must not
    abort verification of every other flag in the content.
    """
    if cmd in help_commands:
        return help_commands[cmd]
    if cmd in allowed_help_cmds:
        try:
            result = subprocess.run(
                [cmd, "--help"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        return result.stdout + result.stderr
    return None
