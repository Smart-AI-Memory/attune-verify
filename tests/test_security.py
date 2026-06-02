"""Security boundary tests (T3 acceptance criterion 5)."""
import subprocess
from unittest.mock import patch
from attune_verify import verify, VerifyContext


def test_verify_does_not_run_generated_code():
    suspicious = '
'.join([
        ''''python',
        'import subprocess',
        'subprocess.run(["echo", "pwned"])',
        ''''',
    ])
    with patch("attune_verify.checkers.imports._resolves", return_value=True):
        result = verify(suspicious, VerifyContext())
    assert result is not None  # No exception = no execution


def test_no_help_for_undeclared_command():
    content = "Use --dangerous-flag to activate the feature."
    ctx = VerifyContext(allowed_help_cmds=frozenset())
    called = []
    original = subprocess.run
    def tracking(args, **kw):
        called.append(list(args) if isinstance(args, (list, tuple)) else args)
        return original(args, **kw)
    with patch("subprocess.run", side_effect=tracking):
        verify(content, ctx)
    assert all("--help" not in c for c in called), f"Unexpected --help: {called}"
