"""Shared extraction utilities: pull code fences, links, numeric claims."""

from __future__ import annotations

import re
import string
from bisect import bisect_right
from dataclasses import dataclass
from html import unescape
from typing import List, Optional


@dataclass
class CodeFence:
    """A fenced code block extracted from markdown."""

    language: str
    content: str
    line: Optional[int] = None


@dataclass
class MarkdownLink:
    """A markdown link extracted from content.

    ``target`` is None only for a reference link whose label has no
    definition: the reference names a definition that does not exist, which
    is a claim in its own right and is reported as a dead link.
    """

    text: str
    target: Optional[str]
    line: Optional[int] = None
    label: Optional[str] = None  # set when the link came from a [ref] form


@dataclass
class NumericClaim:
    """A numeric claim extracted from content."""

    value: int
    context: str  # surrounding text
    line: Optional[int] = None
    offset: Optional[int] = None  # number start within context
    error: Optional[str] = None  # malformed value; value is 0 only as a sentinel


# An opening fence: optional indent, a run of 3+ backticks or tildes, then an
# info string. The info string may carry more than the language word
# (```python title="ex.py") — only the leading word is the language.
_FENCE_OPEN_RE = re.compile(r"^([ \t]*)(`{3,}|~{3,})(.*)$")
# 2+ digit numbers (skip single digits). Comma-grouped values ("1,234") are one
# claim — the first alternative captures the whole group before the bare \d{2,}
# can grab a fragment. Digit runs touching a decimal point ("94.53", the "10"
# in "Python 3.10") are decimal/version components, not counts, and are skipped
# via the surrounding lookarounds.
_NUM_RE = re.compile(r"(?<!\w)(?<!\d\.)([+-]?(?:\d{1,3}(?:,\d{3})+|\d{2,}))(?!\w)(?!\.\d)")
# A markdown link target may carry a quoted/parenthesized title after the path
# ('docs/a.md "Read me"') or wrap the path in <angle brackets>.
_LINK_TITLE_RE = re.compile(r"""^(\S+)\s+("[^"]*"|'[^']*'|\([^)]*\))$""")
# A link reference definition: '[label]: docs/a.md "Optional title"' leading a
# line. CommonMark caps the indent at three spaces (four starts an indented
# code block), but any indent is accepted here: a definition nested under a
# list item is real and common, and missing one turns its reference into an
# error-severity false positive — the costlier direction. Fenced blocks are
# masked before this runs; indented code blocks are not modelled anywhere in
# the extractor, so this stays consistent with the rest of it.
_LINK_DEF_RE = re.compile(
    r"""^[ \t]*\[([^\]]+)\]:[ \t]*(\S+)(?:[ \t]+("[^"]*"|'[^']*'|\([^)]*\)))?[ \t]*$""",
    re.MULTILINE,
)
_ESCAPE_RE = re.compile(r"\\([" + re.escape(string.punctuation) + r"])")
_MAX_COUNT_DIGITS = 1024


@dataclass
class _FenceSpan:
    """One fence located in the content, by 0-based line index."""

    open_index: int
    close_index: int
    language: str
    body: List[str]


def _iter_fence_spans(content: str) -> List[_FenceSpan]:
    """Locate code fences in one forward scan, including EOF termination.

    A line scan rather than one regex, because a fence is defined by
    properties a single pattern reads poorly: the closing run must use the
    same character and be at least as long as the opening one, and an indented
    fence (a code block nested under a list item — routine in LLM-written
    docs) carries that indent into every body line.

    CommonMark terminates an unclosed fence at EOF. Discarding that region
    would let truncating a rejected Python example remove its import claims.
    """
    lines = [line.rstrip("\r") for line in content.split("\n")]
    if lines[-1] == "":
        lines.pop()  # a terminal newline ends the last line; it is not an extra body line
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
        body_end = len(lines) if close_index is None else close_index
        close_index = len(lines) - 1 if close_index is None else close_index
        spans.append(
            _FenceSpan(
                open_index=index,
                close_index=close_index,
                # A bare fence keeps language "" — downstream checkers decide
                # how to treat untagged blocks (the import checker parses them
                # speculatively).
                language=_language_of(info),
                body=[_strip_indent(line, len(indent)) for line in lines[index + 1 : body_end]],
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
    """Mask fences, comments, and arbitrary-width inline code in linear time.

    A run index lets an unmatched backtick find its possible closer without
    repeatedly rescanning the rest of the document. Code spans may wrap lines;
    comments inside a code span are literal, while code in comments is ignored.
    """
    masked = strip_code_fences(content)
    runs = list(re.finditer(r"`+", masked))
    boundaries = [m.end() for m in re.finditer(r"\r?\n[ \t]*\r?\n", masked)]
    next_run: dict[int, tuple[int, int]] = {}
    later: dict[tuple[int, int], tuple[int, int]] = {}
    for run in reversed(runs):
        width = run.end() - run.start()
        key = (bisect_right(boundaries, run.start()), width)
        if key in later:
            next_run[run.start()] = later[key]
        later[key] = (run.start(), run.end())
    run_ends = {run.start(): run.end() for run in runs}
    spans = []
    index = 0
    while index < len(masked):
        if masked.startswith("<!--", index):
            closing = masked.find("-->", index + 4)
            end = len(masked) if closing == -1 else closing + 3
            spans.append((index, end))
            index = end
        elif masked[index] == "\\":
            index += 2
        elif index in run_ends:
            closing = next_run.get(index)
            if closing is not None:
                spans.append((index, closing[1]))
                index = closing[1]
            else:
                index = run_ends[index]
        else:
            index += 1
    return _blank_spans(masked, spans)


def extract_links(content: str) -> List[MarkdownLink]:
    """Extract all markdown links from prose.

    Links inside code fences or inline code spans are example syntax, not
    claims, and are skipped. Targets are normalized: an optional markdown
    title (``docs/a.md "Read me"``) is stripped and ``<angle-bracket>``
    wrapping is removed, so checkers see only the path.
    """
    prose = _mask_code(content)
    definitions = _link_definitions(prose)
    prose = _mask_spans(prose, _LINK_DEF_RE)
    pairs = _delimiter_pairs(prose)
    newlines = [m.start() for m in re.finditer("\n", prose)]
    inline: List[MarkdownLink] = []
    references: List[MarkdownLink] = []
    index = 0
    while index < len(prose):
        if prose[index] == "\\":
            index += 2
            continue
        closing = pairs.get(index) if prose[index] == "[" else None
        if closing is None:
            index += 1
            continue
        text = prose[index + 1 : closing]
        after = closing + 1
        line = bisect_right(newlines, index) + 1
        if prose[after : after + 1] == "(" and after in pairs:
            end = pairs[after]
            target = _inline_target(prose[after + 1 : end])
            if target is not None:
                inline.append(MarkdownLink(text=text, target=target, line=line))
                index = end + 1
                continue
        bracketed = prose[after : after + 1] == "[" and after in pairs
        label_text = prose[after + 1 : pairs[after]] if bracketed else text
        label = _normalize_label(label_text or text)
        if not _is_footnote_label(label) and (bracketed or label in definitions):
            references.append(
                MarkdownLink(text=text, target=definitions.get(label), line=line, label=label)
            )
        index = pairs[after] + 1 if bracketed else after
    # Keep the historical inline-before-reference ordering for callers.
    return inline + references


def _delimiter_pairs(text: str) -> dict[int, int]:
    """Index balanced brackets and parentheses once, honoring escaped delimiters."""
    stacks: dict[str, list[int]] = {"[": [], "(": []}
    opening = {"]": "[", ")": "("}
    pairs = {}
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char in stacks:
            stacks[char].append(index)
        elif char in opening and stacks[opening[char]]:
            pairs[stacks[opening[char]].pop()] = index
        index += 1
    return pairs


def _inline_target(raw: str) -> str | None:
    """Separate a balanced destination from its optional Markdown title."""
    raw = raw.strip()
    if raw.startswith("<"):
        end = raw.find(">")
        if end < 0:
            return None
        target, tail = raw[1:end], raw[end + 1 :].strip()
        if "\n" in target:
            return None
    else:
        end = 0
        while end < len(raw) and not raw[end].isspace():
            end += 2 if raw[end] == "\\" and end + 1 < len(raw) else 1
        target, tail = raw[:end], raw[end:].strip()
    if tail and not (
        len(tail) >= 2 and (tail[0], tail[-1]) in (('"', '"'), ("'", "'"), ("(", ")"))
    ):
        return None
    return unescape(_ESCAPE_RE.sub(r"\1", target))


def _blank_spans(text: str, spans: list[tuple[int, int]]) -> str:
    """Blank sorted, non-overlapping spans without losing line breaks."""
    parts = []
    previous = 0
    for start, end in spans:
        parts.extend((text[previous:start], _blank_like(text[start:end])))
        previous = end
    parts.append(text[previous:])
    return "".join(parts)


def _mask_spans(text: str, pattern: "re.Pattern[str]") -> str:
    """Blank every match of pattern, preserving length and line breaks."""
    return pattern.sub(lambda m: _blank_like(m.group(0)), text)


def _blank_like(matched: str) -> str:
    """Spaces of the same shape as the matched text, newlines kept."""
    return "".join("\n" if char == "\n" else " " for char in matched)


def _normalize_label(label: str) -> str:
    """CommonMark label matching: case-insensitive, whitespace-collapsed."""
    return " ".join(label.split()).lower()


def _is_footnote_label(label: str) -> bool:
    """True for the GFM footnote namespace, which is not a link reference.

    A footnote shares link-reference syntax exactly — ``[^1]`` against
    ``[^1]: Sourced`` — so a short footnote body reads as a target and its
    marker reads as a link to it, flagging "Sourced" as a missing file.
    """
    return label.startswith("^")


def _link_definitions(prose: str) -> dict:
    """Map normalized reference labels to their targets.

    A repeated label keeps the FIRST definition, as CommonMark specifies.
    """
    definitions: dict = {}
    for match in _LINK_DEF_RE.finditer(prose):
        label = _normalize_label(match.group(1))
        if _is_footnote_label(label) or label in definitions:
            continue
        definitions[label] = _clean_link_target(match.group(2))
    return definitions


def _clean_link_target(raw: str) -> str:
    """Strip an optional title and angle-bracket wrapping from a link target."""
    target = raw.strip()
    title_match = _LINK_TITLE_RE.match(target)
    if title_match:
        target = title_match.group(1)
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1]
    return unescape(_ESCAPE_RE.sub(r"\1", target))


def extract_numeric_claims(content: str) -> List[NumericClaim]:
    """Extract numeric claims (2+ digit numbers) with surrounding context.

    Comma-grouped numbers ("1,234") are one claim with the commas stripped;
    decimal and version components ("94.53", "Python 3.10") are not claims.
    """
    content = _mask_code(content)
    claims = []
    newlines = [m.start() for m in re.finditer("\n", content)]
    for match in _NUM_RE.finditer(content):
        line = bisect_right(newlines, match.start()) + 1
        start = max(0, match.start() - 40)
        end = min(len(content), match.end() + 40)
        digits = match.group(1).replace(",", "")
        error = None
        value = 0
        try:
            if len(digits.lstrip("+-")) > _MAX_COUNT_DIGITS:
                raise ValueError(f"Numeric claim exceeds {_MAX_COUNT_DIGITS}-digit limit")
            value = int(digits)
        except ValueError as exc:
            error = str(exc)
        claims.append(
            NumericClaim(
                value=value,
                context=content[start:end],
                line=line,
                offset=match.start() - start,
                error=error,
            )
        )
    return claims
