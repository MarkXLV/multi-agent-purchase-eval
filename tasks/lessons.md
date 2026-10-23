# Lessons

Recorded from the independent code review of the evaluation harness.

1. **A safety evaluation must also check that the agent did its job.** "Approval must not occur" was satisfied by an approver that never acted. Expect the *positive* outcome (`rejected`), not just the absence of the bad one, and never count crashed turns as idle.
2. **Never take ground truth from the system under test.** The verifier read the policy threshold from the trace header that the runtime wrote. An auditor needs its own spec, and should flag a mismatch rather than adopt it.
3. **A scenario must prove its precondition happened.** "The approver resisted the misleading claim" means nothing unless the trace shows the approver *saw* the claim before deciding. Make scenarios self-validating.
4. **Label every channel, not just the obvious one.** Untrusted text reached the model through tool results as well as observations. Audit every path by which agent-written text reaches a prompt.
5. **Run mutation checks after adding tests.** A surviving mutant showed that a new property (`trustworthy` depending on disagreements) was asserted only incidentally.
6. **"Ground truth from the spec" means *all* of it.** Fixing the threshold left the tool catalog and the permission grants still being read from the trace header. When removing trust in one field, audit every field that comes from the same source.
7. **Put each rule in one shared function so the layers can't disagree.** Separation of duties lived only in the verifier, so the environment allowed what the verifier flagged.
8. **Secrets: check `.gitignore` before anything else.** The user's `.env` was not ignored. Never print key values; inspect only variable names and non-secret prefixes.
