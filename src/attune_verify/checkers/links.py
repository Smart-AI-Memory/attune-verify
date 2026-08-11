"""Link checker — verifies markdown link targets resolve to real files."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional
from urllib.parse import unquote

from attune_verify._extract import MarkdownLink
from attune_verify.result import Finding, FindingKind


def check_links(
    links: List[MarkdownLink],
    project_root: Optional[Path],
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
        # Skip external URLs and anchors-only
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        # Strip anchor fragments for file existence check
        path_part = target.split("#")[0]
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
        resolved = _resolve_target(root, rel)
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
    """Resolve a link target under root, honouring percent-encoding.

    A link to a file whose name contains a space is written ``a%20b.md``, and
    checking that literally flagged a file that exists. The raw form is tried
    first, so a file genuinely named ``a%20b.md`` still resolves; the decoded
    form is the fallback, and is only preferred when it exists.
    """
    resolved = (root / rel).resolve()
    if resolved.exists():
        return resolved
    decoded = unquote(rel)
    if decoded == rel:
        return resolved
    decoded_path = (root / decoded).resolve()
    return decoded_path if decoded_path.exists() else resolved
