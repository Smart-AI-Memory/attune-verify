import json

import pytest

from attune_verify import VerifyContext
from attune_verify.evaluation import evaluate
from tests.test_cli import run_cli


def test_metrics_and_human_separation():
    cases = [
        {
            "id": "bad",
            "content": "```python\nimport nonexistent_evaluation_module\n```",
            "expected_error": True,
        },
        {"id": "good", "content": "```python\nimport pathlib\n```", "expected_error": False},
        {"id": "unknown", "content": "There are 42 widgets.", "expected_error": None},
    ]
    report = evaluate({"schema_version": 1, "cases": cases}, VerifyContext())
    assert report["metrics"]["precision"] == 1
    assert report["metrics"]["recall"] == 1
    assert report["unlabeled_cases"] == 1
    assert report["human_validated_metrics"] is None
    cases[0].update(label_basis="human", split="heldout", reviewer="test fixture reviewer")
    assert (
        evaluate({"schema_version": 1, "cases": cases}, VerifyContext())["human_validated_metrics"][
            "documents"
        ]
        == 1
    )


@pytest.mark.parametrize(
    "corpus",
    [
        {},
        {"schema_version": 1, "cases": [None]},
        {"schema_version": 1, "cases": [{"content": "", "expected_error": 1}]},
        {
            "schema_version": 1,
            "cases": [{"content": "", "label_basis": "human", "split": "heldout"}],
        },
    ],
)
def test_invalid_labels(corpus):
    with pytest.raises(ValueError):
        evaluate(corpus, VerifyContext())


def test_evaluate_cli_and_empty_metrics(tmp_path):
    path = tmp_path / "corpus.json"
    path.write_text('{"schema_version": 1, "cases": []}')
    process = run_cli(tmp_path, "evaluate", str(path))
    assert process.returncode == 0
    report = json.loads(process.stdout)
    assert report["metrics"]["precision"] is None
    assert report["human_validated_metrics"] is None
