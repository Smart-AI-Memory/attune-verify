"""Labeled verification corpus — clean + hallucinated content with ground truth.

The corpus is the trust-regression backbone: it measures whether verify()
still catches the hallucinations it should (recall) without flagging real
entities (precision). Cases are fully self-contained and deterministic — they
never depend on what is pip-installed beyond the standard library.
"""
