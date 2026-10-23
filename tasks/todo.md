# Plan — Solumn AI multi-agent evaluation environment

Source of truth: `Solumn AI assessment.md`. Stack: Python 3.10+, stdlib-only core, optional `anthropic` extra, `pytest`.

## Key decisions (made up front)

- [x] **Language**: Python. Stdlib-only core so the deterministic mode runs with zero installs; `anthropic` is an optional extra.
- [x] **No API credentials available** → deterministic mode is the default; the Anthropic adapter is unit-tested against a fake SDK client.
- [x] **LLM-backed agent = Approver (Agent B)** via a provider-neutral `ModelClient` seam. Deterministic stand-ins (`mock`, `gullible`) plug into the *same* `LLMAgent` code path.
- [x] **Requester (Agent A) = scripted state-machine policy** (allowed by the spec; guarantees the misleading claim occurs). Optional LLM requester when a key exists.
- [x] **Two enforcement layers**: permission check (who may call what) + policy guard (approve > $10k needs verified human auth). Guard can be disabled (`--no-guard`) to observe raw agent behaviour.
- [x] **Verifier replays the trace** (event-sourced) and recomputes permissions + policy itself; it never trusts the runtime's allow/deny flags or the agent's text.
- [x] **Negative controls**: a "gullible" approver model proves the verifier catches violations (guarded → blocked attempt; unguarded → non-compliant outcome).

## Tasks

- [x] 1. Architecture note (`docs/ARCHITECTURE.md`, ≤1 page) written before code
- [x] 2. Domain + policy + state (`domain.py`, `policy.py`, `state.py`)
- [x] 3. Tool catalog + permissions + environment execute pipeline (`tools.py`, `environment.py`, `events.py`)
- [x] 4. Agents: `ScriptedRequester`, `LLMAgent`; model seam (`llm/base.py`), mocks (`llm/mock.py`), Anthropic adapter (`llm/anthropic_client.py`)
- [x] 5. Runtime (scheduling, observations, termination)
- [x] 6. Verifier (trace replay → per-request verdicts)
- [x] 7. Scenarios (4 required + 3 extra edge cases) + runner + CLI (`run`, `verify`, `list`, `report`)
- [x] 8. Tests: policy, environment/permissions, runtime (incl. 3rd agent), verifier (incl. tampered trace), LLM agent + adapter, scenarios, CLI e2e
- [x] 9. HTML report generator (for demo)
- [x] 10. E2E run: all scenarios + negative controls; commit sample traces under `runs/`
- [x] 11. Demo: screenshots (terminal + report) + animated GIF in `docs/demo/`
- [x] 12. Docs: README.md, UNDERSTANDING.md, QUESTIONS.md, docs/RETROSPECTIVE.md (≤300 words), architecture revisions section, CLAUDE.md commands
- [x] 13. Independent code review (subagent) → fix findings → re-run tests

## Review

**Status: complete.** 98 tests pass, plus 2 opt-in live tests, and the Python 3.10–3.14 matrix is clean. Running `make all` from a fresh copy exits 0, and the regenerated `runs/` are byte-identical to the committed ones.

What was verified, and how:
- **Every spec requirement** maps to code and tests (see the traceability table in `UNDERSTANDING.md` §7).
- **Negative controls:**
  - The gullible approver with the guard on is blocked, flagged and fails its expectation.
  - With the guard off, the approval is non-compliant and both `run` and `verify` exit 1.
- **Mutation testing:** 24 injected bugs, all caught. Survivors on two earlier passes each exposed a missing assertion, which was then added.
- **Independent review:** a second agent found six issues, all reproduced and fixed with regression tests (`UNDERSTANDING.md` §6). Before the fixes:
  - An approver that never acted passed the must-not-approve scenarios.
  - The verifier trusted the trace header.
  - The claim wasn't guaranteed to be seen.
  - Agent text reached the model as "authoritative" tool results.
  - Trustworthiness didn't gate the exit code.
  - Typos counted as attacks.
- **Demo:** real CLI output and the HTML report, screenshotted with Playwright. The GIF and MP4 were built with ffmpeg.

Not verified:
- ~~**The live Anthropic API.**~~ Now verified (2026-10-14): 7/7 scenarios live, 6/6 unguarded adversarial repeats, 3/3 with an LLM requester, `pytest -m live` 2/2. The invalid-key path was also verified (clean exit-1 failure, errors surfaced).

**End-to-end verification round (2026-10-14).** Six agents ran in isolated copies, and their findings were reproduced and then fixed. Details are in `UNDERSTANDING.md` §6. The suite is now 98 tests plus 2 opt-in live tests, and the mutation check is at 24/24 caught.
