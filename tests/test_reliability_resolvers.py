"""Resolver receipts assert exact subjects and preserve evidence across failures."""

import ast
import os
import subprocess
import sys
from unittest.mock import patch

import pytest

from attune_verify import VerifyContext, verify


@pytest.fixture
def parser_help(tmp_path):
    script = tmp_path / "sample.py"
    script.write_text(
        "import argparse\n"
        "p = argparse.ArgumentParser(prog='sample', allow_abbrev=False)\n"
        "p.add_argument('--verbose', action='store_true')\n"
        "p.add_argument('--message')\n"
        "p.add_argument('files', nargs='*')\n"
        "p.parse_args()\n"
    )
    help_text = subprocess.run(
        [sys.executable, str(script), "--help"], capture_output=True, text=True, check=True
    ).stdout
    return script, help_text


@pytest.mark.parametrize("fenced", [False, True])
@pytest.mark.parametrize(
    "command,argv,subjects,accepted",
    [
        ("sample --verbose.extra", ["--verbose.extra"], ["sample --verbose.extra"], False),
        ("sample --verbose -- --ghost", ["--verbose", "--", "--ghost"], ["sample --verbose"], True),
        ('sample --message="--ghost"', ["--message=--ghost"], ["sample --message"], True),
    ],
)
def test_flag_subjects_match_actual_argument_tokens(
    parser_help, fenced, command, argv, subjects, accepted
):
    script, help_text = parser_help
    oracle = subprocess.run([sys.executable, str(script), *argv], capture_output=True)
    assert (oracle.returncode == 0) is accepted
    content = f"```sh\n{command}\n```" if fenced else f"`{command}`"
    result = verify(content, VerifyContext(help_commands={"sample": help_text}))
    assert [c.subject for c in result.claims] == subjects
    assert result.passes() is accepted


def test_help_does_not_verify_punctuation_prefix():
    result = verify(
        "`sample --verbose`", VerifyContext(help_commands={"sample": "--verbose.extra"})
    )
    assert not result.passes()


@pytest.mark.skipif(os.name != "posix", reason="fixed POSIX shell argument oracle")
@pytest.mark.parametrize("fenced", [False, True])
@pytest.mark.parametrize(
    "arguments,subject,accepted",
    [
        ("--verbose#bad", "sample --verbose#bad", False),
        ("--verbose # comment --ghost", "sample --verbose", True),
        (r"--verbose\#bad", "sample --verbose#bad", False),
        ('"--verbose#bad"', "sample --verbose#bad", False),
        ("--verbose''#bad", "sample --verbose#bad", False),
    ],
)
def test_hash_comments_follow_shell_word_boundaries(
    parser_help, fenced, arguments, subject, accepted
):
    script, help_text = parser_help
    # Execute only fixed test arguments, never arbitrary document contents.
    oracle = subprocess.run(
        ["/bin/sh", "-c", '"$FIXTURE_PYTHON" "$FIXTURE_SCRIPT" ' + arguments],
        env={**os.environ, "FIXTURE_PYTHON": sys.executable, "FIXTURE_SCRIPT": str(script)},
        capture_output=True,
    )
    assert (oracle.returncode == 0) is accepted
    command = "sample " + arguments
    content = f"```sh\n{command}\n```" if fenced else f"`{command}`"
    result = verify(content, VerifyContext(help_commands={"sample": help_text}))
    assert [c.subject for c in result.claims] == [subject]
    assert result.passes() is accepted


@pytest.mark.skipif(os.name == "nt", reason="real executable fixture uses a POSIX shebang")
def test_invalid_utf8_help_preserves_prior_and_later_claims(tmp_path):
    command = tmp_path / "noisy-help"
    command.write_text(f"#!{sys.executable}\nimport os\nos.write(1, b'\\xff')\n")
    command.chmod(0o700)
    result = verify(
        f"`sample --ghost`\n`{command} --bad`\n`sample --verbose`",
        VerifyContext(
            help_commands={"sample": "--verbose"}, allowed_help_cmds=frozenset({str(command)})
        ),
    )
    assert [c.status.value for c in result.claims] == ["refuted", "unknown", "verified"]
    assert not result.ok
    assert "utf-8" in result.claims[1].detail.lower()


def test_invalid_utf8_import_preserves_prior_and_later_claims(tmp_path, monkeypatch):
    (tmp_path / "noisy_fixture_01.py").write_text("import os\nos.write(1, b'\\xff')\nVALUE=1\n")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    result = verify(
        "```python\nimport missing_fixture_01\nfrom noisy_fixture_01 import VALUE\nimport os\n```",
        VerifyContext(),
    )
    assert [c.status.value for c in result.claims] == ["refuted", "unknown", "verified"]
    assert not result.ok


def test_python_parse_recursion_preserves_other_fence_claims():
    oversized_expression = "+" * 5000 + "1"
    try:
        ast.parse(oversized_expression)
    except (RecursionError, MemoryError) as exc:
        parse_failure = type(exc).__name__
    else:
        parse_failure = None
    content = (
        "```python\nimport missing_fixture_parse_01\n```\n"
        f"```python\n{oversized_expression}\n```\n"
        "```python\nimport os\n```"
    )
    result = verify(content, VerifyContext())
    if parse_failure:
        assert [c.subject for c in result.claims] == [
            "missing_fixture_parse_01",
            "Python syntax",
            "os",
        ]
        assert [c.status.value for c in result.claims] == ["refuted", "unknown", "verified"]
        assert [c.location for c in result.claims] == ["line 2", "line 5", "line 8"]
        assert result.claims[1].evidence.strip() == oversized_expression
        assert parse_failure in result.claims[1].detail
    else:
        # Some supported interpreters can parse this expression. It contains
        # no import and therefore contributes no claim when parsing succeeds.
        assert [c.subject for c in result.claims] == ["missing_fixture_parse_01", "os"]
        assert [c.status.value for c in result.claims] == ["refuted", "verified"]
        assert [c.location for c in result.claims] == ["line 2", "line 8"]
    assert not result.ok


@pytest.mark.parametrize("error", [RecursionError, MemoryError])
def test_python_parse_resource_failure_preserves_other_fences(error):
    original_parse = ast.parse

    def bounded_parse(content, *args, **kwargs):
        if content.strip() == "middle_fixture_expression":
            raise error("fixture parse resource limit")
        return original_parse(content, *args, **kwargs)

    with patch("attune_verify.checkers.imports.ast.parse", side_effect=bounded_parse):
        result = verify(
            "```python\nimport missing_fixture_parse_01\n```\n"
            "```python\nmiddle_fixture_expression\n```\n"
            "```python\nimport os\n```",
            VerifyContext(),
        )
    assert [c.subject for c in result.claims] == ["missing_fixture_parse_01", "Python syntax", "os"]
    assert [c.status.value for c in result.claims] == ["refuted", "unknown", "verified"]
    assert [c.location for c in result.claims] == ["line 2", "line 5", "line 8"]
    assert error.__name__ in result.claims[1].detail
    assert not result.ok


def test_python_syntax_error_stays_refuted_among_other_fences():
    result = verify(
        "```python\nimport missing_fixture_parse_01\n```\n"
        "```python\nif:\n```\n"
        "```python\nimport os\n```",
        VerifyContext(),
    )
    assert [c.status.value for c in result.claims] == ["refuted", "refuted", "verified"]
    assert result.claims[1].subject == "Python syntax"


@pytest.mark.skipif(os.name == "nt", reason="real executable fixture uses a POSIX shebang")
def test_failed_help_runs_once_and_keeps_each_location(tmp_path):
    command = tmp_path / "failed-help"
    marker = tmp_path / "attempts"
    command.write_text(
        f"#!{sys.executable}\nfrom pathlib import Path\n"
        f"with Path({str(marker)!r}).open('a') as f: f.write('attempt\\n')\n"
        "raise SystemExit(1)\n"
    )
    command.chmod(0o700)
    result = verify(
        f"`{command} --one --two`\n`{command} --one`",
        VerifyContext(allowed_help_cmds=frozenset({str(command)})),
    )
    assert marker.read_text().splitlines() == ["attempt"]
    assert [c.status.value for c in result.claims] == ["unknown"] * 3
    assert [c.location for c in result.claims] == ["line 1", "line 1", "line 2"]


def test_failed_import_probe_is_cached():
    from attune_verify._extract import CodeFence
    from attune_verify.checkers.imports import check_imports

    claims = []
    with patch(
        "attune_verify.checkers.imports._resolves", side_effect=RuntimeError("failed")
    ) as probe:
        check_imports([CodeFence("python", "import fixture\nimport fixture\n")], claims=claims)
    assert probe.call_count == 1
    assert [c.status.value for c in claims] == ["unknown", "unknown"]


@pytest.mark.parametrize("payload", ["bad json", '{"exists": "yes"}', "[]", "{}"])
def test_bad_probe_payload_is_unknown_without_erasing_claims(payload):
    import attune_verify.checkers.imports as module

    # The fixed program is trusted; protocol corruption is a provider failure.
    with patch.object(module, "_PROBE", f"print('ATTUNE_PROBE:' + {payload!r})"):
        result = verify("```python\nimport os\nimport sys\n```", VerifyContext())
    assert [c.status.value for c in result.claims] == ["unknown", "unknown"]
    assert not result.passes()
