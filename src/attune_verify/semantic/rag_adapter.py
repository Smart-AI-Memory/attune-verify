"""Optional rag adapter for the semantic layer.

Only imported when the [rag] extra is installed.
Provides make_rag_judge() which wraps attune-rag's FaithfulnessJudge.

Phase-3 verification item: confirm FaithfulnessResult field names
(is_faithful / unsupported_claims) against installed attune-rag before
wiring this adapter.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, List, Union

from attune_verify.semantic.protocol import SemanticVerdict

if TYPE_CHECKING:
    from attune_verify.semantic.protocol import Judge


def make_rag_judge(**kwargs: object) -> "Judge":
    """Build a Judge wrapping attune-rag's FaithfulnessJudge.

    Args:
        **kwargs: Passed directly to FaithfulnessJudge.__init__
            (api_key, model, timeout, etc.).

    Returns:
        A Judge-compatible adapter.

    Raises:
        ImportError: If attune-rag is not installed (install attune-verify[rag]).
    """
    try:
        from attune_rag.eval.faithfulness import FaithfulnessJudge  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError(
            "attune-rag is required for the semantic layer. "
            "Install with: pip install 'attune-verify[rag]'"
        ) from exc

    inner = FaithfulnessJudge(**kwargs)

    class _Adapter:
        def score(
            self,
            query: str,
            answer: str,
            passages: Union[str, List[str]],
        ) -> SemanticVerdict:
            # FaithfulnessJudge.score() is async — run synchronously here.
            # TODO(Phase-3): verify is_faithful / unsupported_claims field names
            # against installed attune-rag before relying on them.
            result = asyncio.run(inner.score(query, answer, passages))
            return SemanticVerdict(
                faithful=result.is_faithful,  # type: ignore[attr-defined]
                issues=result.unsupported_claims or [],  # type: ignore[attr-defined]
                raw=result,
            )

    return _Adapter()  # type: ignore[return-value]
