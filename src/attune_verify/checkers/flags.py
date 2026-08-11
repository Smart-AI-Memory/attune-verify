"""Flag checker — verifies CLI flags referenced in content exist in --help."""

from __future__ import annotations

import re
import subprocess
from typing import Dict, FrozenSet, List, Optional

from attune_verify._extract import extract_code_fences, strip_code_fences
from attune_verify.result import Finding, FindingKind

# One inline code span (`mytool --flag`); fences are handled separately.
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
# A flag token anywhere in code text: long (--flag) or short (-f, -xzf, -name).
# Stops before "=value"; the negative lookbehind keeps it from matching the tail
# of a longer flag, a hyphenated word, or a "---" rule. A short flag must start
# with a LETTER, so a negative number argument ("--threshold -5") is not read as
# a flag — the one shape where a dash-number is far more often a value.
_FLAG_TOKEN_RE = re.compile(r"(?<![\w-])(--\w[\w-]*|-[A-Za-z][\w-]*)")
# A short flag carrying its value with no space ("-j4", "-O2").
_ATTACHED_VALUE_RE = re.compile(r"-([A-Za-z])\d+\Z")
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
    if _flag_in_help(flag, help_text):
        return None
    reading = _alternate_reading(flag, help_text)
    if reading is not None:
        return None
    if _is_ambiguous_short(flag):
        # '-xzf' may be a cluster, '-name' a single-dash long option, '-j4' a
        # flag with an attached value. None of those readings verified, but the
        # token is genuinely ambiguous, so calling it refuted would risk a
        # false error on a real flag. Unverifiable -> warning, never a silent
        # pass — the same rule as a command with no --help.
        return Finding(
            kind=FindingKind.UNKNOWN_FLAG,
            detail=(
                f"Short flag '{flag}' could not be verified against "
                f"'{cmd} --help' — not found whole, as a cluster of "
                "single-letter flags, or as a flag with an attached value"
            ),
            evidence=evidence,
            severity="warning",
        )
    return Finding(
        kind=FindingKind.UNKNOWN_FLAG,
        detail=f"Flag '{flag}' not found in '{cmd} --help'",
        evidence=evidence,
        severity="error",
    )


def _is_ambiguous_short(flag: str) -> bool:
    """True for a single-dash token longer than one letter.

    ``-v`` is unambiguous: it is that flag or nothing. ``-xzf`` is not — it
    could be three flags, one flag, or a flag plus a value.
    """
    return not flag.startswith("--") and len(flag) > 2


def _alternate_reading(flag: str, help_text: str) -> Optional[List[str]]:
    """Return the first alternate reading of a short flag that fully verifies.

    Only single-dash tokens have alternate readings. A cluster verifies when
    EVERY letter is a known flag (``-xzf`` against ``-x -z -f``); an attached
    value verifies when the leading flag is known (``-j4`` against ``-j``).
    """
    if not _is_ambiguous_short(flag):
        return None
    body = flag[1:]
    if body.isalpha():
        cluster = [f"-{letter}" for letter in body]
        if all(_flag_in_help(part, help_text) for part in cluster):
            return cluster
    attached = _ATTACHED_VALUE_RE.fullmatch(flag)
    if attached and _flag_in_help(f"-{attached.group(1)}", help_text):
        return [f"-{attached.group(1)}"]
    return None


def _flag_in_help(flag: str, help_text: str) -> bool:
    """Return True if flag appears in help as a whole token.

    A plain substring test gives false negatives: ``--ver`` would pass
    because ``--verbose`` contains it. Require the flag be bounded on BOTH
    sides by a non-flag character — the trailing bound stops ``-v`` matching
    inside ``--verbose``, and the leading bound stops it matching the tail of
    ``--v``, which would verify a short flag the command does not have.
    """
    return re.search(r"(?<![\w-])" + re.escape(flag) + r"(?![\w-])", help_text) is not None


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
