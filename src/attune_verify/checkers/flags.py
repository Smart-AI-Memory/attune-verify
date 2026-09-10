"""Flag checker — verifies CLI flags referenced in content exist in --help."""

from __future__ import annotations

import re
import shlex
import subprocess
from typing import Dict, FrozenSet, List, Optional

from attune_verify._extract import extract_code_fences, strip_code_fences
from attune_verify._process import probe_scope, run_probe
from attune_verify.claims import Claim, record
from attune_verify.result import Finding, FindingKind

# One inline code span (`mytool --flag`); fences are handled separately.
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
# Classify the beginning only; the whole shell token is retained as evidence.
# Short options start with a letter, so negative numbers remain values.
_FLAG_START_RE = re.compile(r"(?:--\w|-[A-Za-z])")
# A short flag carrying its value with no space ("-j4", "-O2").
_ATTACHED_VALUE_RE = re.compile(r"-([A-Za-z])\d+\Z")
# Fence languages whose content is command lines worth flag-checking.
_SHELL_LANGS = frozenset({"bash", "sh", "shell", "console", "zsh"})


def check_flags(
    content: str,
    help_commands: Dict[str, str],
    allowed_help_cmds: FrozenSet[str],
    *,
    claims: list[Claim] | None = None,
    help_executables: dict[str, str] | None = None,
) -> List[Finding]:
    """Verify flags referenced in content exist in command --help output.

    Security: only invokes --help for commands in allowed_help_cmds.
    A flag for an unknown command yields a warning, not a silent pass.

    Args:
        content: Generated content to scan for flag references.
        help_commands: Pre-captured --help text keyed by command name.
        allowed_help_cmds: Commands safe to invoke at runtime.
        help_executables: Optional alias-to-executable paths from a manifest.

    Returns:
        List of findings for unverifiable or unknown flags.
    """
    with probe_scope():
        return _check_flags(
            content, help_commands, allowed_help_cmds, claims, help_executables or {}
        )


def _check_flags(
    content: str,
    help_commands: dict[str, str],
    allowed_help_cmds: FrozenSet[str],
    claims: list[Claim] | None,
    help_executables: dict[str, str],
) -> list[Finding]:
    findings: List[Finding] = []
    captured = set(help_commands)
    help_commands = dict(help_commands)  # includes cached failures (None)
    failures: dict[str, str] = {}
    commands = set(help_commands) | set(allowed_help_cmds)

    def check_line(text: str, evidence: str, location: str, preceding: str = "") -> None:
        cmd = _command(text, commands)
        if cmd == "unknown" and text.lstrip().startswith("-"):
            cmd = _guess_command(preceding)
        for flag in _flag_tokens(text):
            finding = _verify_flag(
                flag,
                cmd,
                evidence,
                help_commands,
                allowed_help_cmds,
                help_executables=help_executables,
                failures=failures,
            )
            if finding is not None:
                finding = Finding(
                    finding.kind, finding.detail, finding.evidence, location, finding.severity
                )
                findings.append(finding)
            source = cmd if cmd in captured else help_executables.get(cmd, cmd)
            record(claims, "flags", f"{cmd} {flag}", evidence, location, finding, source=source)

    # Inline spans: `--flag` alone or a whole command in one span
    # (`mytool --flag`). Fence bodies are stripped first so they are never
    # double-scanned as inline code.
    prose = strip_code_fences(content)
    for match in _INLINE_CODE_RE.finditer(prose):
        span = match.group(1)
        check_line(
            span,
            f"`{span}`",
            f"line {prose[:match.start()].count(chr(10)) + 1}",
            prose[max(0, match.start() - 30) : match.start()],
        )
    # Shell fences: each line is a command whose flags are claims too.
    for fence in extract_code_fences(content):
        if fence.language not in _SHELL_LANGS:
            continue
        for index, line in enumerate(fence.content.splitlines(), start=1):
            command_line = line.strip().lstrip("$").strip()
            check_line(command_line, command_line, f"line {(fence.line or 0) + index}")
    return findings


def _flag_tokens(text: str) -> list[str]:
    """Read complete options, omitting attached values and operands after --."""
    text = _without_shell_comment(text)
    try:
        words = shlex.split(text)
    except ValueError:
        # Malformed quoting still exposes claims, with an unknown command.
        words = text.split()
    flags = []
    for word in words:
        if word == "--":
            break
        if _FLAG_START_RE.match(word):
            flags.append(word.partition("=")[0])
    return flags


def _without_shell_comment(text: str) -> str:
    """A shell comment starts at an unquoted word boundary, not inside argv."""
    quote = None
    escaped = False
    in_word = False
    for index, char in enumerate(text):
        if escaped:
            escaped = False
            continue
        if quote == "'":
            if char == "'":
                quote = None
            continue
        if char == "\\":
            escaped = True
            in_word = True
            continue
        if quote == '"':
            if char == '"':
                quote = None
            continue
        if char in "\"'":
            quote = char
            in_word = True
        elif char.isspace():
            in_word = False
        elif char == "#" and not in_word:
            return text[:index]
        else:
            in_word = True
    return text


def _verify_flag(
    flag: str,
    cmd: str,
    evidence: str,
    help_commands: dict[str, str | None],
    allowed_help_cmds: FrozenSet[str],
    *,
    help_executables: dict[str, str] | None = None,
    failures: dict[str, str] | None = None,
) -> Optional[Finding]:
    """Check one flag against its command's help; None when it verifies."""
    help_text = _get_help(
        cmd, help_commands, allowed_help_cmds, help_executables=help_executables, failures=failures
    )
    if help_text is None:
        reason = (failures or {}).get(cmd)
        return Finding(
            kind=FindingKind.UNKNOWN_FLAG,
            detail=(
                f"Flag '{flag}' could not be verified "
                f"(no --help output available for command '{cmd}'"
                + (f": {reason}" if reason else "")
                + ")"
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
    return (
        re.search(r"(?<![\w.\-/:])" + re.escape(flag) + r"(?=$|[\s=,\[\](){}<>])", help_text)
        is not None
    )


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
    help_commands: dict[str, str | None],
    allowed_help_cmds: FrozenSet[str],
    *,
    help_executables: dict[str, str] | None = None,
    failures: dict[str, str] | None = None,
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
            executable = (help_executables or {}).get(cmd, cmd)
            result = run_probe([executable, "--help"])
        except (OSError, subprocess.TimeoutExpired, RuntimeError, ValueError, TypeError) as exc:
            help_commands[cmd] = None
            if failures is not None:
                failures[cmd] = str(exc)
            return None
        if result.returncode:
            help_commands[cmd] = None
            if failures is not None:
                failures[cmd] = f"help command exited with status {result.returncode}"
            return None
        help_commands[cmd] = result.stdout + result.stderr
        return help_commands[cmd]
    return None


def _command(text: str, declared: set[str]) -> str:
    """Use a declared command prefix, not the last positional argument.

    Complex shell syntax remains unknown rather than being attributed to the
    wrong command. Never execute generated argument strings.
    """
    text = _without_shell_comment(text)
    try:
        words = shlex.split(text)
    except ValueError:
        return "unknown"
    if not words or words[0].startswith("-"):
        return "unknown"
    if any(token in text for token in (";", "|", "&&", "$(", "`")):
        return "unknown"
    candidates = []
    for cmd in declared:
        try:
            prefix = shlex.split(cmd)
        except ValueError:
            continue
        if prefix and words[: len(prefix)] == prefix:
            candidates.append((len(prefix), cmd))
    return max(candidates)[1] if candidates else words[0]
