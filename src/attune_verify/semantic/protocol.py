"""Judge protocol for attune-verify's semantic layer.

The core library never imports attune-rag directly. Any object satisfying
Judge can be injected: the built-in rag adapter, a skill-judge, or a fake.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Protocol, Union, runtime_checkable


@dataclass
class SemanticVerdict:
    """Result from a Judge.score() call."""

    faithful: bool
    issues: List[str] = field(default_factory=list)
    raw: object = None  # underlying result, for debugging


@runtime_checkable
class Judge(Protocol):
    """Protocol that any semantic judge must satisfy.

    Signature matches attune-rag's FaithfulnessJudge.score() so the
    rag adapter is near-trivial (verified against rag 0.2.0).
    """

    def score(
        self,
        query: str,
        answer: str,
        passages: Union[str, List[str]],
    ) -> SemanticVerdict:
        """Score the faithfulness of answer relative to passages.

        Args:
            query: The original question or intent.
            answer: The generated content to verify.
            passages: Source passage(s) the answer should be grounded in.

        Returns:
            SemanticVerdict with faithful flag and any identified issues.
        """
        ...
