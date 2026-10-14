# Retrospective

**What I would improve.**
- Run many more live trials per scenario and report rates. Live Claude passed 7/7 scenarios and 6/6 unguarded adversarial repeats, but that's a handful of samples.
- Add harder adversarial pressure: fake "registry exports" pasted into messages, authority impersonation, and urgency spread over several turns.
- Add mid-episode events, such as a human granting or revoking authorization.

**What I would not trust yet.**
- **The Anthropic adapter's edge paths.** It works live, but refusals and fallbacks (`fallbacks` goes through `extra_body`) were only exercised with a fake client.
- **The shared `policy.py`.** The verifier is independent of the runtime's *enforcement path*, but it imports the same rules. A wrong rule would be wrong in both places, and only explicit boundary tests guard against that.
- **The mocks.** They prove the plumbing and verifier work, not that an LLM is safe.
- **Multi-request runs.** Expectations assume one request per scenario.

**How I validated the AI-generated code.**
1. I wrote the architecture note first, then checked the code against it and logged the deviations.
2. I wrote tests from the spec, not from the code. Each §2.D requirement has named verifier tests.
3. I added negative controls. A gullible approver must make the suite fail: blocked but flagged with the guard on, and non-compliant with the guard off.
4. I mutation-tested the suite. Each of 24 injected bugs, such as `>=` for `>`, a disabled guard, or a verifier trusting the trace header, was caught by at least one test.
5. Hand-tampered traces prove the verifier relies on events, not runtime flags.
6. Clean-venv installs on Python 3.10 and 3.14.
7. An independent agent review found six real issues, including that an approver that never acted passed "must not approve". All six were fixed with regression tests.
