"""Link checker — verifies markdown link targets resolve to real files."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from attune_verify._extract import MarkdownLink
from attune_verify.result import Finding, FindingKind


def check_links(
    links: List[MarkdownLink],
    project_root: Optional[Path],
) -> List[Finding]:
    """Verify markdown link targets exist relative to project_root.

    External URLs (http/https) are skipped — only local paths are checked.

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
        # Skip external URLs and anchors-only
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        # Strip anchor fragments for file existence check
        path_part = target.split("#")[0]
        if not path_part:
            continue
        if project_root is None:
            findings.append(Finding(
                kind=FindingKind.DEAD_LINK,
                detail=(
                    f"Link '{target}' cannot be verified "
                    "(no project_root in VerifyContext)"
                ),
                evidence=f"[{link.text}]({link.target})",
                location=f"line {link.line}" if link.line else None,
                severity="warning",
            ))
            continue
        resolved = (project_root / path_part).resolve()
        if not resolved.exists():
            findings.append(Finding(
                kind=FindingKind.DEAD_LINK,
                detail=f"Link target '{path_part}' does not exist",
                evidence=f"[{link.text}]({link.target})",
                location=f"line {link.line}" if link.line else None,
                severity="error",
            ))
    return findings
