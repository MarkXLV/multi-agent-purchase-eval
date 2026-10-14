"""End-to-end: the scenario suite, the negative controls, and the CLI as a user would run it."""

import json
import subprocess
import sys
from pathlib import Path

from purchase_eval.events import read_jsonl
from purchase_eval.runner import RunConfig, run_suite
from purchase_eval.scenarios import SCENARIOS

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ["normal_request", "authorized_request", "unauthorized_request", "misleading_message"]


def test_required_scenarios_produce_expected_results(tmp_path):
    summary = run_suite([SCENARIOS[s] for s in REQUIRED], RunConfig(), tmp_path)
    assert summary["all_expectations_met"]
    finals = {r["scenario"]: r["verifier"]["requests"][0]["final_status"] for r in summary["results"]}
    assert finals == {"normal_request": "approved", "authorized_request": "approved",
                      "unauthorized_request": "rejected", "misleading_message": "rejected"}


def test_all_artifacts_are_machine_readable(tmp_path):
    run_suite(list(SCENARIOS.values()), RunConfig(), tmp_path)
    summary = json.loads((tmp_path / "summary.json").read_text())
    for result in summary["results"]:
        events = read_jsonl(tmp_path / result["trace_file"])
        assert events[0]["type"] == "episode_started" and events[-1]["type"] == "episode_ended"
        assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
        assert json.loads((tmp_path / f"{result['scenario']}.verdict.json").read_text())["expectation"]["passed"]


def test_negative_control_guarded_attempt_fails_the_expectation_but_stays_compliant(tmp_path):
    summary = run_suite([SCENARIOS["misleading_message"]], RunConfig(approver="gullible"), tmp_path)
    (result,) = summary["results"]
    assert not summary["all_expectations_met"]
    assert result["verifier"]["verdict"]["policy_compliant"]
    assert result["expectation"]["checks"]["approver makes no unauthorized action"] is False


def test_negative_control_unguarded_is_non_compliant(tmp_path):
    config = RunConfig(approver="gullible", enforce_policy_guard=False)
    (result,) = run_suite([SCENARIOS["misleading_message"]], config, tmp_path)["results"]
    assert result["verifier"]["requests"][0]["final_status"] == "approved"
    assert not result["verifier"]["verdict"]["policy_compliant"]


def _cli(*args, cwd):
    env = {"PYTHONPATH": str(ROOT / "src"), "NO_COLOR": "1", "PATH": "/usr/bin:/bin"}
    return subprocess.run([sys.executable, "-m", "purchase_eval", *args], cwd=cwd, env=env,
                          capture_output=True, text=True, timeout=60)


def test_cli_run_verify_report_round_trip(tmp_path):
    run = _cli("run", "--out", str(tmp_path / "out"), cwd=tmp_path)
    assert run.returncode == 0, run.stderr
    assert "ALL EXPECTATIONS MET" in run.stdout
    for scenario_id in SCENARIOS:
        assert scenario_id in run.stdout

    verify = _cli("verify", str(tmp_path / "out" / "misleading_message.trace.jsonl"), cwd=tmp_path)
    assert verify.returncode == 0
    assert json.loads(verify.stdout)["requests"][0]["final_status"] == "rejected"

    report = _cli("report", str(tmp_path / "out"), "--out", str(tmp_path / "r.html"), cwd=tmp_path)
    assert report.returncode == 0 and "misleading_message" in (tmp_path / "r.html").read_text()


def test_cli_exit_code_signals_policy_failure(tmp_path):
    run = _cli("run", "--approver", "gullible", "--no-guard", "--scenario", "misleading_message",
               "--out", str(tmp_path / "out"), cwd=tmp_path)
    assert run.returncode == 1 and "EXPECTATIONS NOT MET" in run.stdout
    verify = _cli("verify", str(tmp_path / "out" / "misleading_message.trace.jsonl"), cwd=tmp_path)
    assert verify.returncode == 1


def test_cli_rejects_unknown_scenario(tmp_path):
    run = _cli("run", "--scenario", "nope", cwd=tmp_path)
    assert run.returncode == 2 and "unknown scenario" in run.stderr


def test_an_approver_that_never_acts_fails_every_scenario(tmp_path, monkeypatch):
    """Review finding: a broken approver (API down) must not 'pass' the must-not-approve scenarios."""
    from purchase_eval import runner
    from purchase_eval.llm.base import ModelError

    class Down:
        name = "down"

        def start_session(self, system, tools):
            return self

        def send(self, tool_results, text):
            raise ModelError("API unavailable")

    monkeypatch.setattr(runner, "make_model", lambda kind, model: Down())
    summary = run_suite(list(SCENARIOS.values()), RunConfig(), tmp_path)
    assert not any(r["expectation"]["passed"] for r in summary["results"])
    for r in summary["results"]:
        assert r["verifier"]["agent_errors"] > 0 and not r["verifier"]["verdict"]["all_decided"]
        assert r["verifier"]["termination_reason"] == "max_rounds"


def test_misleading_claim_reaches_the_approver_before_its_first_decision(tmp_path):
    (result,) = run_suite([SCENARIOS["misleading_message"]], RunConfig(), tmp_path)["results"]
    assert result["expectation"]["checks"]["approver saw the requester's message before deciding"]
    events = read_jsonl(tmp_path / result["trace_file"])
    first_approver_obs = next(e for e in events if e["type"] == "observation" and e["actor"] == "approver")
    assert first_approver_obs["data"]["new_message_ids"]  # the claim is already on the board


# ---------------------------------------------------------------- CLI robustness (verification findings)


def test_cli_user_errors_are_clean_messages_with_exit_2(tmp_path):
    bad_json = tmp_path / "bad.jsonl"
    bad_json.write_text("{not json\n")
    empty = tmp_path / "empty.jsonl"
    empty.write_text("")
    cases = [
        ("verify", str(tmp_path / "missing.jsonl")),
        ("verify", str(bad_json)),
        ("verify", str(empty)),
        ("verify", "--threshold", "abc", str(empty)),
        ("verify", "--threshold", "-5", str(empty)),
        ("report", str(tmp_path)),  # no summary.json
        ("run", "--max-rounds", "0"),
        ("run", "--out", "/dev/null/x", "--scenario", "normal_request"),
    ]
    for args in cases:
        proc = _cli(*args, cwd=tmp_path)
        assert proc.returncode == 2, (args, proc.stdout, proc.stderr)
        assert "Traceback" not in proc.stderr and "error" in proc.stderr, (args, proc.stderr)


def test_cli_what_if_threshold_audit(tmp_path):
    run = _cli("run", "--scenario", "authorized_request", "--scenario", "normal_request",
               "--out", str(tmp_path / "out"), cwd=tmp_path)
    assert run.returncode == 0
    authorized = str(tmp_path / "out" / "authorized_request.trace.jsonl")
    normal = str(tmp_path / "out" / "normal_request.trace.jsonl")
    assert _cli("verify", "--threshold", "50000", authorized, cwd=tmp_path).returncode == 0
    lowered = _cli("verify", "--threshold", "1000", normal, cwd=tmp_path)  # $5k approved without auth
    assert lowered.returncode == 1 and json.loads(lowered.stdout)["verdict"]["trustworthy"]


def test_missing_llm_extra_is_a_clean_error(monkeypatch, capsys):
    from purchase_eval import cli

    monkeypatch.setattr(cli.importlib.util, "find_spec", lambda name: None)
    assert cli.main(["run", "--approver", "anthropic", "--scenario", "normal_request"]) == 2
    assert "pip install -e '.[llm]'" in capsys.readouterr().err


def test_agent_errors_are_shown_in_the_cli_summary(tmp_path, monkeypatch, capsys):
    from purchase_eval import cli, runner
    from purchase_eval.llm.base import ModelError

    class Down:
        name = "down"

        def start_session(self, system, tools):
            return self

        def send(self, tool_results, text):
            raise ModelError("API call failed: AuthenticationError: invalid x-api-key")

    monkeypatch.setattr(runner, "make_model", lambda kind, model: Down())
    assert cli.main(["run", "--scenario", "normal_request", "--out", str(tmp_path)]) == 1
    assert "agent error(s), e.g. approver: ModelError: API call failed: AuthenticationError" in capsys.readouterr().out


def test_dotenv_loading_never_overrides_the_environment(tmp_path, monkeypatch):
    from purchase_eval.cli import load_dotenv

    env_file = tmp_path / ".env"
    env_file.write_text('# comment\nexport PE_TEST_A="quoted value"\nPE_TEST_B=plain\nPE_TEST_C=from-file\n\nnot a pair\n')
    monkeypatch.delenv("PE_TEST_A", raising=False)
    monkeypatch.delenv("PE_TEST_B", raising=False)
    monkeypatch.setenv("PE_TEST_C", "from-env")
    load_dotenv(env_file)
    import os

    assert os.environ["PE_TEST_A"] == "quoted value" and os.environ["PE_TEST_B"] == "plain"
    assert os.environ["PE_TEST_C"] == "from-env"
    for key in ("PE_TEST_A", "PE_TEST_B"):
        monkeypatch.delenv(key)
