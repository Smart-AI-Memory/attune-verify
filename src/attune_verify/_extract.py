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


# The opening fence may carry an info string after the language word
# (```python title="ex.py") — [^\n]* consumes it so those fences are still
# extracted; only the leading word is the language.
_FENCE_RE = re.compile(
    r"^```(\w*)[^\n]*\n(.*?)^```",
    re.MULTILINE | re.DOTALL,
)
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
# 2+ digit numbers (skip single digits). Comma-grouped values ("1,234") are one
# claim — the first alternative captures the whole group before the bare \d{2,}
# can grab a fragment. Digit runs touching a decimal point ("94.53", the "10"
# in "Python 3.10") are decimal/version components, not counts, and are skipped
# via the surrounding lookarounds.
_NUM_RE = re.compile(r"(?<!\w)(?<!\d\.)(\d{1,3}(?:,\d{3})+|\d{2,})(?!\w)(?!\.\d)")
# A markdown link target may carry a quoted/parenthesized title after the path
# ('docs/a.md "Read me"') or wrap the path in <angle brackets>.
_LINK_TITLE_RE = re.compile(r"""^(\S+)\s+("[^"]*"|'[^']*'|\([^)]*\))$""")


def extract_code_fences(content: str) -> List[CodeFence]:
    """Extract all fenced code blocks from markdown content."""
    fences = []
    for match in _FENCE_RE.finditer(content):
        line = content[: match.start()].count("\n") + 1
        # A bare fence keeps language "" — downstream checkers decide how to
        # treat untagged blocks (the import checker parses them speculatively).
        fences.append(
            CodeFence(
                language=match.group(1),
                content=match.group(2),
                line=line,
            )
        )
    return fences


def extract_links(content: str) -> List[MarkdownLink]:
    """Extract all markdown links from content.

    Targets are normalized: an optional markdown title
    (``docs/a.md "Read me"``) is stripped and ``<angle-bracket>`` wrapping is
    removed, so checkers see only the path.
    """
    links = []
    for match in _LINK_RE.finditer(content):
        line = content[: match.start()].count("\n") + 1
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
