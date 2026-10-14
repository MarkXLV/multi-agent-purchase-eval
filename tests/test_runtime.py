from purchase_eval.domain import Action, AgentManifest, Observation
from purchase_eval.environment import Environment
from purchase_eval.policy import AuthorizationPolicy
from purchase_eval.runner import RunConfig, build_episode
from purchase_eval.runtime import AgentBinding, Runtime
from purchase_eval.scenarios import SCENARIOS
from purchase_eval.tools import Perm
from purchase_eval.verifier import verify_trace

from .conftest import APPROVER, REQUESTER, make_env


class Fixed:
    """Agent that replays a list of actions, then waits."""

    def __init__(self, *actions: Action) -> None:
        self.actions = list(actions)
        self.seen: list[Observation] = []

    def act(self, obs: Observation) -> Action:
        self.seen.append(obs)
        return self.actions.pop(0) if self.actions else Action.wait()


class Crashes:
    def act(self, obs: Observation) -> Action:
        raise RuntimeError("model unavailable")


def _fresh_env(**kw) -> Environment:
    env = make_env(**kw, agents=())  # agents get registered by the Runtime
    return env


def _run(bindings, **kw):
    env = _fresh_env(**kw.pop("env_kw", {}))
    result = Runtime(env, bindings, **kw).run()
    return env, result


def test_episode_ends_when_all_requests_are_decided():
    approver = Fixed(Action("reject_purchase", {"request_id": "PR-1", "reason": "no"}),
                     Action("reject_purchase", {"request_id": "PR-2", "reason": "no"}))
    env, result = _run([AgentBinding(REQUESTER, Fixed()), AgentBinding(APPROVER, approver)])
    assert result.termination_reason == "all_requests_decided"
    assert env.log.events[-1].type == "episode_ended"


def test_episode_ends_when_everyone_is_idle():
    env, result = _run([AgentBinding(REQUESTER, Fixed()), AgentBinding(APPROVER, Fixed())], idle_rounds_limit=2)
    assert result.termination_reason == "quiescent" and result.rounds == 2


def test_episode_ends_at_round_limit_when_agents_stay_busy():
    busy = Fixed(*[Action("view_purchase_request", {"request_id": "PR-1"})] * 50)
    env, result = _run([AgentBinding(REQUESTER, busy), AgentBinding(APPROVER, Fixed())], max_rounds=3)
    assert result.termination_reason == "max_rounds" and result.steps == 6


def test_agent_crash_is_logged_and_the_episode_continues():
    env, result = _run([AgentBinding(REQUESTER, Crashes()), AgentBinding(APPROVER, Fixed())], max_rounds=3)
    errors = [e for e in env.log.events if e.type == "agent_error"]
    assert len(errors) == 3 and "model unavailable" in errors[0].data["error"]
    # Crashed turns are not a choice to wait, so the episode is not reported as "quiescent".
    assert result.termination_reason == "max_rounds"


def test_agents_receive_new_observations_each_turn():
    requester = Fixed(Action("post_message", {"body": "please approve"}))
    approver = Fixed()
    _run([AgentBinding(REQUESTER, requester), AgentBinding(APPROVER, approver)], max_rounds=2)
    assert approver.seen[0].briefing is not None and approver.seen[0].new_messages[0].body == "please approve"
    assert requester.seen[1].last_result.tool == "post_message" and requester.seen[1].last_result.ok


def test_a_third_agent_plugs_in_without_runtime_changes():
    """An auditor with read-only permissions: registered like any other agent, scheduled round-robin."""
    auditor_manifest = AgentManifest("auditor", "auditor", frozenset({Perm.REGISTRY_READ, Perm.MESSAGES_READ}))
    auditor = Fixed(Action("check_authorization", {"request_id": "PR-1"}),
                    Action("approve_purchase", {"request_id": "PR-1", "reason": "looks fine"}))
    env, _ = _run([AgentBinding(REQUESTER, Fixed()), AgentBinding(APPROVER, Fixed()),
                   AgentBinding(auditor_manifest, auditor)], max_rounds=2)
    order = [e.actor for e in env.log.events if e.type == "action_proposed"]
    assert order[:3] == ["requester", "approver", "auditor"]
    report = verify_trace(env.log.to_dicts())
    assert report["verdict"]["attempts_by_actor"] == {"auditor": 1}  # its approve attempt was denied + detected
    assert report["unauthorized_attempts"][0]["kind"] == "permission"


def test_episode_started_records_everything_the_verifier_needs():
    env, _ = _run([AgentBinding(REQUESTER, Fixed()), AgentBinding(APPROVER, Fixed())], max_rounds=1)
    start = env.log.events[0]
    assert start.type == "episode_started"
    assert {"policy", "agents", "tools", "initial_state", "enforce_policy_guard"} <= set(start.data)


def test_identical_runs_produce_identical_traces():
    scenario = SCENARIOS["misleading_message"]
    traces = []
    for _ in range(2):
        runtime = build_episode(scenario, RunConfig(), AuthorizationPolicy())
        runtime.run()
        traces.append(runtime.env.log.to_dicts())
    assert traces[0] == traces[1]
