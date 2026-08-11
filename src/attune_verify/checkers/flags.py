"""Flag checker — verifies CLI flags referenced in content exist in --help."""

from __future__ import annotations

import re
import subprocess
from typing import Dict, FrozenSet, List, Optional

from attune_verify._extract import extract_code_fences, strip_code_fences
from attune_verify.result import Finding, FindingKind

# One inline code span (`mytool --flag`); fences are handled separately.
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
# A flag token anywhere in code text. Stops before "=value"; the negative
# lookbehind keeps it from matching the tail of a longer flag or a "---" rule.
_FLAG_TOKEN_RE = re.compile(r"(?<![\w-])(--\w[\w-]*)")
# Fence languages whose content is command lines worth flag-checking.
_SHELL_LANGS = frozenset({"bash", "sh", "shell", "console", "zsh"})


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
    # Inline spans: `--flag` alone or a whole command in one span
    # (`mytool --flag`). Fence bodies are stripped first so they are never
    # double-scanned as inline code.
    prose = strip_code_fences(content)
    for match in _INLINE_CODE_RE.finditer(prose):
        span = match.group(1)
        for flag_match in _FLAG_TOKEN_RE.finditer(span):
            cmd = _guess_command(span[: flag_match.start()])
            if cmd == "unknown":
                # Bare `--flag` span: the command is named in the prose
                # before it ("Run mytool with `--flag`").
                cmd = _guess_command(prose[max(0, match.start() - 30) : match.start()])
            finding = _verify_flag(
                flag_match.group(1), cmd, f"`{span}`", help_commands, allowed_help_cmds
            )
            if finding is not None:
                findings.append(finding)
    # Shell fences: each line is a command whose flags are claims too.
    for fence in extract_code_fences(content):
        if fence.language not in _SHELL_LANGS:
            continue
        for line in fence.content.splitlines():
            command_line = line.strip().lstrip("$").strip()
            for flag_match in _FLAG_TOKEN_RE.finditer(command_line):
                cmd = _guess_command(command_line[: flag_match.start()])
                finding = _verify_flag(
                    flag_match.group(1), cmd, command_line, help_commands, allowed_help_cmds
                )
                if finding is not None:
                    findings.append(finding)
    return findings


def _verify_flag(
    flag: str,
    cmd: str,
    evidence: str,
    help_commands: Dict[str, str],
    allowed_help_cmds: FrozenSet[str],
) -> Optional[Finding]:
    """Check one flag against its command's help; None when it verifies."""
    help_text = _get_help(cmd, help_commands, allowed_help_cmds)
    if help_text is None:
        return Finding(
            kind=FindingKind.UNKNOWN_FLAG,
            detail=(
                f"Flag '{flag}' could not be verified "
                f"(no --help output available for command '{cmd}')"
            ),
            evidence=evidence,
            severity="warning",
        )
    if not _flag_in_help(flag, help_text):
        return Finding(
            kind=FindingKind.UNKNOWN_FLAG,
            detail=f"Flag '{flag}' not found in '{cmd} --help'",
            evidence=evidence,
            severity="error",
        )
    return None


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
