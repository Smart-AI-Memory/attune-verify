"""Link checker — verifies markdown link targets resolve to real files."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional
from urllib.parse import unquote, urlsplit

from attune_verify._extract import MarkdownLink
from attune_verify.claims import Claim, record
from attune_verify.result import Finding, FindingKind


def _check_links(
    links: List[MarkdownLink],
    project_root: Optional[Path],
    document_path: Optional[Path] = None,
) -> List[Finding]:
    """Verify markdown link targets exist relative to project_root.

    External URLs (http/https) are skipped — only local paths are checked.
    A reference link whose label has no definition is reported directly: the
    reference names a definition that does not exist, so there is no target
    to look up.

    Args:
        links: Markdown links extracted from generated content.
        project_root: Root directory for relative path resolution.
            If None, all local links yield warnings (cannot verify).

    Returns:
        List of findings for dead links.
    """
    findings: List[Finding] = []
    for link in links:
        target = link.target
        if target is None:
            # An undefined reference does not render as a link at all — the
            # raw '[text][label]' is what a reader sees. Refuted, not
            # unverifiable, so this is an error like any other dead link.
            findings.append(
                Finding(
                    kind=FindingKind.DEAD_LINK,
                    detail=(
                        f"Link reference '[{link.label}]' is used but never "
                        "defined — no matching '[label]: target' definition"
                    ),
                    evidence=_evidence(link),
                    location=f"line {link.line}" if link.line else None,
                    severity="error",
                )
            )
            continue
        # URL components have meaning before filesystem resolution. In
        # particular a query is not part of a filename and schemes ignore case.
        if "\x00" in target:
            raise ValueError("Link target contains NUL")
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc or target.startswith("#"):
            continue
        path_part = parsed.path
        if not path_part:
            continue
        if project_root is None:
            findings.append(
                Finding(
                    kind=FindingKind.DEAD_LINK,
                    detail=(
                        f"Link '{target}' cannot be verified " "(no project_root in VerifyContext)"
                    ),
                    evidence=_evidence(link),
                    location=f"line {link.line}" if link.line else None,
                    severity="warning",
                )
            )
            continue
        root = project_root.resolve()
        # Site-absolute targets (/docs/page.md) mean root-relative in generated
        # docs; joining them raw would make Path use the filesystem root.
        rel = path_part.lstrip("/") if path_part.startswith("/") else path_part
        base = root
        if document_path is not None and not path_part.startswith("/"):
            document = (root / document_path).resolve()
            if not document.is_relative_to(root):
                raise ValueError("document_path escapes project_root")
            base = document.parent
        resolved = _resolve_target(base, rel)
        if not resolved.is_relative_to(root):
            # ../-traversal out of the declared truth boundary: the file may
            # exist on disk, but it cannot be verified AS a project link.
            # Warning, not error — same "never a silent pass" rule as flags.
            findings.append(
                Finding(
                    kind=FindingKind.DEAD_LINK,
                    detail=(
                        f"Link '{target}' resolves outside project_root " "and cannot be verified"
                    ),
                    evidence=_evidence(link),
                    location=f"line {link.line}" if link.line else None,
                    severity="warning",
                )
            )
            continue
        if not resolved.exists():
            findings.append(
                Finding(
                    kind=FindingKind.DEAD_LINK,
                    detail=f"Link target '{path_part}' does not exist",
                    evidence=_evidence(link),
                    location=f"line {link.line}" if link.line else None,
                    severity="error",
                )
            )
    return findings


def _evidence(link: MarkdownLink) -> str:
    """Render the link the way it was written.

    A reference link quoted back as inline syntax would be evidence the reader
    cannot find in their document, so reference forms keep their brackets.
    """
    if link.label is not None:
        return f"[{link.text}][{link.label}]"
    return f"[{link.text}]({link.target})"


def _resolve_target(root: Path, rel: str) -> Path:
    """Resolve the decoded URL path, never an alternative existing spelling."""
    return (root / unquote(rel, errors="strict")).resolve()


def check_links(
    links: List[MarkdownLink],
    project_root: Optional[Path],
    *,
    claims: list[Claim] | None = None,
    document_path: Optional[Path] = None,
) -> List[Finding]:
    """Check local files and explicitly account for unsupported URL/anchor checks."""
    findings = []
    for link in links:
        target = link.target or f"reference:{link.label}"
        unknown = None
        try:
            checked = _check_links([link], project_root, document_path)
            if link.target:
                parsed = urlsplit(link.target)
                if parsed.scheme or parsed.netloc:
                    unknown = "External targets are not fetched"
                elif "#" in link.target:
                    unknown = "File existence does not verify a heading fragment"
        except (ValueError, OSError, RuntimeError) as exc:
            # Invalid URLs, NUL paths, permission errors and symlink loops
            # belong to this claim. They must not discard earlier refutations.
            checked = [
                Finding(
                    kind=FindingKind.DEAD_LINK,
                    detail=f"Link '{target}' cannot be verified: {exc}",
                    evidence=_evidence(link),
                    location=f"line {link.line}" if link.line else None,
                    severity="warning",
                )
            ]
        findings.extend(checked)
        record(
            claims,
            "links",
            target,
            _evidence(link),
            f"line {link.line}" if link.line else None,
            checked[0] if checked else None,
            unknown=unknown,
            source=str(project_root) if project_root is not None else None,
        )
    return findings
