"""Actual child imports: initializer output/errors and nonexecuted fence body."""

from attune_verify import VerifyContext, verify


def test_generated_statements_never_execute(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    (tmp_path / "noisy_fixture.py").write_text("print('hello initializer')\nVALUE = 1\n")
    marker = tmp_path / "must-not-exist"
    result = verify(
        "```python\nfrom noisy_fixture import VALUE\n"
        f"open({str(marker)!r}, 'w').write('bad')\n```",
        VerifyContext(),
    )
    assert result.passes()
    assert not marker.exists()


def test_missing_transitive_dependency_is_unknown(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    (tmp_path / "broken_fixture.py").write_text("import missing_transitive_dependency_fixture\n")
    result = verify("```python\nfrom broken_fixture import VALUE\n```", VerifyContext())
    assert result.ok
    assert result.status == "unknown"
    assert "missing_transitive_dependency_fixture" in result.findings[0].detail
