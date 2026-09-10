"""Security boundary tests (T3 acceptance criterion 5)."""

from unittest.mock import patch

from attune_verify import VerifyContext, verify


def test_verify_does_not_run_generated_code():
    suspicious = "\n".join(
        [
            "```python",
            "import subprocess",
            'subprocess.run(["echo", "pwned"])',
            "```",
        ]
    )
    with (
        patch("attune_verify.checkers.imports._resolves", return_value=True),
        patch("attune_verify._process.subprocess.Popen") as spawn,
    ):
        result = verify(suspicious, VerifyContext())
    spawn.assert_not_called()
    assert result is not None  # No exception = no execution


def test_no_help_for_undeclared_command():
    content = "Use `undeclared-command --dangerous-flag` to activate the feature."
    ctx = VerifyContext(allowed_help_cmds=frozenset())
    with patch("attune_verify._process.subprocess.Popen") as spawn:
        result = verify(content, ctx)
    spawn.assert_not_called()
    assert result.claims[0].status == "unknown"
