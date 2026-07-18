"""Optional rag adapter for the semantic layer.

Only imported when the [rag] extra is installed.
Provides make_rag_judge() which wraps attune-rag's FaithfulnessJudge.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, List, Union

from attune_verify.semantic.protocol import SemanticVerdict

if TYPE_CHECKING:
    from attune_verify.semantic.protocol import Judge


def _to_verdict(result: object) -> SemanticVerdict:
    """Translate attune-rag's FaithfulnessResult into a SemanticVerdict.

    FaithfulnessResult carries no boolean verdict — its ``score`` is
    ``supported / (supported + unsupported)`` — so "faithful" here means
    no unsupported claims were found.
    """
    unsupported = list(getattr(result, "unsupported_claims", None) or [])
    return SemanticVerdict(
        faithful=not unsupported,
        issues=unsupported,
        raw=result,
    )


def make_rag_judge(**kwargs: object) -> "Judge":
    """Build a Judge wrapping attune-rag's FaithfulnessJudge.

    The returned Judge is synchronous: FaithfulnessJudge.score() is async
    and is driven with asyncio.run(), so it must be called from sync code
    (or a worker thread) — never from inside a running event loop.

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
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                pass  # no running loop — safe to drive the coroutine
            else:
                # asyncio.run() inside a running loop raises anyway, but with
                # a message that doesn't say what to do about it.
                raise RuntimeError(
                    "make_rag_judge()'s Judge is synchronous and cannot be "
                    "called from inside a running event loop; call verify() "
                    "from sync code or run it in a worker thread."
                )
            result = asyncio.run(inner.score(query, answer, passages))
            return _to_verdict(result)

    return _Adapter()  # type: ignore[return-value]
