"""Shared extraction utilities: pull code fences, links, numeric claims."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class CodeFence:
    """A fenced code block extracted from markdown."""

    language: str
    content: str
    line: Optional[int] = None


@dataclass
class MarkdownLink:
    """A markdown link extracted from content."""

    text: str
    target: str
    line: Optional[int] = None


@dataclass
class NumericClaim:
    """A numeric claim extracted from content."""

    value: int
    context: str  # surrounding text
    line: Optional[int] = None


# An opening fence: optional indent, a run of 3+ backticks or tildes, then an
# info string. The info string may carry more than the language word
# (```python title="ex.py") — only the leading word is the language.
_FENCE_OPEN_RE = re.compile(r"^([ \t]*)(`{3,}|~{3,})(.*)$")
# A link target may contain one level of balanced parentheses — 'docs/a(1).md'
# is a legal CommonMark target, and [^)]+ truncated it to 'docs/a(1', flagging
# a file that exists.
_LINK_RE = re.compile(r"\[([^\]]+)\]\(((?:[^()]|\([^()]*\))*)\)")
# One inline code span — its contents are shown, not claimed. The delimiter is
# a run of backticks closed by a run of the same length, so a span that itself
# contains backticks (``` ``a `b` c`` ```) is masked whole rather than leaving
# its middle exposed as prose.
_INLINE_CODE_RE = re.compile(r"(?<!`)(`{1,3})(?!`)[^\n]*?(?<!`)\1(?!`)")
# 2+ digit numbers (skip single digits). Comma-grouped values ("1,234") are one
# claim — the first alternative captures the whole group before the bare \d{2,}
# can grab a fragment. Digit runs touching a decimal point ("94.53", the "10"
# in "Python 3.10") are decimal/version components, not counts, and are skipped
# via the surrounding lookarounds.
_NUM_RE = re.compile(r"(?<!\w)(?<!\d\.)(\d{1,3}(?:,\d{3})+|\d{2,})(?!\w)(?!\.\d)")
# A markdown link target may carry a quoted/parenthesized title after the path
# ('docs/a.md "Read me"') or wrap the path in <angle brackets>.
_LINK_TITLE_RE = re.compile(r"""^(\S+)\s+("[^"]*"|'[^']*'|\([^)]*\))$""")


@dataclass
class _FenceSpan:
    """One fence located in the content, by 0-based line index."""

    open_index: int
    close_index: int
    language: str
    body: List[str]


def _iter_fence_spans(content: str) -> List[_FenceSpan]:
    """Locate every closed code fence, line by line.

    A line scan rather than one regex, because a fence is defined by
    properties a single pattern reads poorly: the closing run must use the
    same character and be at least as long as the opening one, and an indented
    fence (a code block nested under a list item — routine in LLM-written
    docs) carries that indent into every body line.

    An unclosed fence is not a fence: its "body" is the rest of the document,
    so treating it as code would drag ordinary prose into the checkers.
    """
    lines = [line.rstrip("\r") for line in content.split("\n")]
    spans: List[_FenceSpan] = []
    index = 0
    while index < len(lines):
        opening = _FENCE_OPEN_RE.match(lines[index])
        if opening is None:
            index += 1
            continue
        indent, marker, info = opening.groups()
        # A tilde fence's info string is unrestricted; a backtick fence's must
        # not contain a backtick, else ``` `code` in prose ``` opens a fence.
        if marker[0] == "`" and "`" in info:
            index += 1
            continue
        close_re = re.compile(rf"^[ \t]*{re.escape(marker[0])}{{{len(marker)},}}[ \t]*$")
        close_index = next(
            (j for j in range(index + 1, len(lines)) if close_re.match(lines[j])),
            None,
        )
        if close_index is None:
            index += 1
            continue
        spans.append(
            _FenceSpan(
                open_index=index,
                close_index=close_index,
                # A bare fence keeps language "" — downstream checkers decide
                # how to treat untagged blocks (the import checker parses them
                # speculatively).
                language=_language_of(info),
                body=[_strip_indent(line, len(indent)) for line in lines[index + 1 : close_index]],
            )
        )
        index = close_index + 1
    return spans


def _language_of(info: str) -> str:
    """Return the leading language word of a fence info string.

    An info string may carry more than the language (```python title="ex.py"),
    and the language itself may be followed by punctuation.
    """
    first = info.strip().split(maxsplit=1)
    return re.match(r"\w*", first[0]).group(0) if first else ""


def _strip_indent(line: str, width: int) -> str:
    """Remove up to ``width`` leading spaces/tabs — the fence's own indent.

    Without this, a fence nested under a list item yields uniformly indented
    code that fails ``ast.parse``, so every import inside it went unchecked.
    """
    removed = 0
    while removed < width and line[:1] in (" ", "\t"):
        line = line[1:]
        removed += 1
    return line


def extract_code_fences(content: str) -> List[CodeFence]:
    """Extract all fenced code blocks from markdown content.

    Backtick and tilde fences are both recognized, at any indentation; a
    fence's own indent is stripped from its body so nested blocks parse.
    """
    return [
        CodeFence(
            language=span.language,
            content="".join(f"{line}\n" for line in span.body),
            line=span.open_index + 1,
        )
        for span in _iter_fence_spans(content)
    ]


def strip_code_fences(content: str) -> str:
    """Blank out every fence, keeping line count and prose offsets intact.

    Fence lines become empty rather than disappearing, so prose either side of
    a block never becomes adjacent — a checker looking backwards for context
    must not read across a code block it was told to ignore.
    """
    lines = content.split("\n")
    for span in _iter_fence_spans(content):
        for index in range(span.open_index, span.close_index + 1):
            lines[index] = ""
    return "\n".join(lines)


def _mask_code(content: str) -> str:
    """Blank code fences and inline spans, preserving every line break.

    Link syntax shown as an example — ``Write it as `[text](target.md)` `` —
    is not a link: no renderer resolves it, so checking it flags a target that
    was never claimed to exist. Masking keeps line offsets intact, so a link's
    reported line number is still its line in the original content.
    """
    masked = strip_code_fences(content)
    return _INLINE_CODE_RE.sub(lambda m: " " * len(m.group(0)), masked)


def extract_links(content: str) -> List[MarkdownLink]:
    """Extract all markdown links from prose.

    Links inside code fences or inline code spans are example syntax, not
    claims, and are skipped. Targets are normalized: an optional markdown
    title (``docs/a.md "Read me"``) is stripped and ``<angle-bracket>``
    wrapping is removed, so checkers see only the path.
    """
    links = []
    prose = _mask_code(content)
    for match in _LINK_RE.finditer(prose):
        line = prose[: match.start()].count("\n") + 1
        links.append(
            MarkdownLink(
                text=match.group(1),
                target=_clean_link_target(match.group(2)),
                line=line,
            )
        )
    return links


def _clean_link_target(raw: str) -> str:
    """Strip an optional title and angle-bracket wrapping from a link target."""
    target = raw.strip()
    title_match = _LINK_TITLE_RE.match(target)
    if title_match:
        target = title_match.group(1)
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1]
    return target


def extract_numeric_claims(content: str) -> List[NumericClaim]:
    """Extract numeric claims (2+ digit numbers) with surrounding context.

    Comma-grouped numbers ("1,234") are one claim with the commas stripped;
    decimal and version components ("94.53", "Python 3.10") are not claims.
    """
    claims = []
    for match in _NUM_RE.finditer(content):
        line = content[: match.start()].count("\n") + 1
        start = max(0, match.start() - 40)
        end = min(len(content), match.end() + 40)
        claims.append(
            NumericClaim(
                value=int(match.group(1).replace(",", "")),
                context=content[start:end].replace("\n", " "),
                line=line,
            )
        )
    return claims
