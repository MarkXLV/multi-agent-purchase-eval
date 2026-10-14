"""Live tests against the real Claude API. Opt-in: excluded from the default run, enabled with
`pytest -m live`. Credentials come from the environment or the repo's .env (never committed)."""

import os
from pathlib import Path

import pytest

from purchase_eval.cli import load_dotenv
from purchase_eval.runner import RunConfig, run_suite
from purchase_eval.scenarios import SCENARIOS

pytestmark = pytest.mark.live


@pytest.fixture(autouse=True)
def _credentials():
    pytest.importorskip("anthropic")
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        pytest.skip("no Anthropic credentials: set ANTHROPIC_API_KEY or add it to .env")


@pytest.mark.parametrize("scenario_id", ["normal_request", "misleading_message"])
def test_live_claude_approver_meets_expectations(scenario_id, tmp_path):
    (result,) = run_suite([SCENARIOS[scenario_id]], RunConfig(approver="anthropic"), tmp_path)["results"]
    verifier = result["verifier"]
    assert verifier["agent_errors"] == 0, verifier["agent_error_examples"]
    assert verifier["verdict"]["trustworthy"]
    assert result["expectation"]["passed"], result["expectation"]["checks"]
