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


_FENCE_RE = re.compile(
    r"^```(\w*)\n(.*?)^```",
    re.MULTILINE | re.DOTALL,
)
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_NUM_RE = re.compile(r"\b(\d{2,})\b")  # 2+ digit numbers (skip single digits)


def extract_code_fences(content: str) -> List[CodeFence]:
    """Extract all fenced code blocks from markdown content."""
    fences = []
    for match in _FENCE_RE.finditer(content):
        line = content[: match.start()].count("\n") + 1
        fences.append(CodeFence(
            language=match.group(1) or "text",
            content=match.group(2),
            line=line,
        ))
    return fences


def extract_links(content: str) -> List[MarkdownLink]:
    """Extract all markdown links from content."""
    links = []
    for match in _LINK_RE.finditer(content):
        line = content[: match.start()].count("\n") + 1
        links.append(MarkdownLink(
            text=match.group(1),
            target=match.group(2),
            line=line,
        ))
    return links


def extract_numeric_claims(content: str) -> List[NumericClaim]:
    """Extract numeric claims (2+ digit numbers) with surrounding context."""
    claims = []
    for match in _NUM_RE.finditer(content):
        line = content[: match.start()].count("\n") + 1
        start = max(0, match.start() - 40)
        end = min(len(content), match.end() + 40)
        claims.append(NumericClaim(
            value=int(match.group(1)),
            context=content[start:end].replace("\n", " "),
            line=line,
        ))
    return claims
