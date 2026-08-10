# Critique rubric

Read this when running critique mode. The object of review is the **workflow's
architecture** — how work is divided between deterministic code, model calls, and people,
and how information and control flow between them. It is not a code review of what the
workflow produces.

Before applying the rubric, reconstruct a spec (per `spec-schema.md`) from whatever the
user has: a script, a set of prompts, a skill, a CI config, a diagram, or a verbal
description. Reconstructing it is itself diagnostic — the parts you cannot fill in are
usually the parts that are actually broken. If you cannot determine what happens when a
node fails, that is finding #9, not a gap in your research.

Report findings ranked by expected cost, not by how many you found. Three real ones beat
eleven padded ones, and a rubric applied exhaustively to a small workflow produces mostly
noise. If the workflow is sound, say so plainly.

---

## 1. Agent-shaped code

**Symptom:** a model call whose output is fully determined by its input. Moving a ticket
between columns. Formatting. Computing a branch name. Choosing between two options by a
rule that could be written as an `if`.

**Cost:** latency and money on every run, plus a nonzero rate of doing it wrong — and a
step that is right 99% of the time is much harder to debug than one that is right always
or never, because the failures are rare enough to look like flakes.

**Fix:** convert to a `code` node.

## 2. Swallowed loop

**Symptom:** validation happens inside a producing agent's turn — the build prompt says
"run the tests and fix any failures" — rather than as a separate node with a failure edge.

**Cost:** you cannot count attempts, cannot cap them, cannot see the check output, cannot
route failure anywhere other than back to the same agent, and cannot change the model on
either half independently.

**Fix:** split into producer and checker nodes with an explicit failure edge. See step 5
of `design-method.md` for the full reasoning.

## 3. Unbounded retry

**Symptom:** a failure edge loops back with no `max_attempts`, or with a bound that exists
in prose but not in code.

**Cost:** an agent that cannot solve a problem will keep not solving it, expensively.
Unattended, this is the failure mode that produces a surprising invoice.

**Fix:** set `max_attempts` and an `on_exhausted` on every node a failure edge targets.

## 4. Amnesiac retry

**Symptom:** failure routes back to a fresh invocation of the producing agent, with the
error appended to a cold prompt.

**Cost:** the agent re-derives everything it already knew, spending tokens to reach the
state it was in when it failed — and often makes a different first mistake instead of
fixing the reported one.

**Fix:** resume the producer's prior session and deliver only the new information: what
failed and how.

## 5. Human in the middle

**Symptom:** synchronous approval gates at interior nodes whose next action is reversible.

**Cost:** throughput is capped at one person's attention no matter how much compute is
available, and the person becomes a bottleneck precisely when the workflow is most useful
(many runs at once).

**Fix:** keep human touchpoints at intake and acceptance, plus any node whose next action
is genuinely irreversible or expensive to undo. Replace "I want to see the plan" with a
written plan payload reviewable after the fact.

## 6. Implicit handoff

**Symptom:** edges with no named payload. State passed by leaving files in the working
directory, or by assuming an agent remembers something from an earlier step.

**Cost:** works until a node is retried, reordered, parallelized, or isolated — then fails
in a way that is very hard to trace, because the missing thing was never named.

**Fix:** name the payload on every edge and make it a real file in a run directory.

## 7. Monolith node

**Symptom:** one agent scouts, plans, builds, and verifies in a single call.

**Cost:** no intermediate state to inspect, retry granularity is the whole job, one model
tier for four very different tasks, and a context window carrying everything at once.

**Fix:** split at the boundaries described in step 2 of `design-method.md`.

## 8. Uniform model selection

**Symptom:** the same model on every agent node — and the same *backend*, since no single
system reaches every model. `claude` everywhere is the common case, but the pattern also
shows up as `codex` or `agy` everywhere once a workflow adopts one of them.

**Cost:** either overpaying for mechanical steps or underpowering the decision steps.
Underpowered scouting and planning are the expensive direction — errors there propagate
through everything downstream and get faithfully implemented. A mechanical node that could
run for free on a self-hosted model but doesn't is a different cost: not wrong, just paid
for no reason.

**Fix:** tier per node, and consider `backend` alongside tier. Strongest for scout and
plan, cheapest that works for mechanical transforms — an `openai-compat` node is often the
right cheapest for narrow classification or reformatting. If a node already runs
self-hosted, check that something can reject its output: a self-hosted node with no fail
edge routing back to it is [pattern 9](#9-missing-failure-path) wearing this one's clothes,
and the classifier's own report is the last place to catch it — a bad route often does not
fail, it just quietly under-serves.

## 9. Missing failure path

**Symptom:** the workflow has a happy path only. Nodes with a `pass` edge and no `fail`
edge; no `on_exhausted`; no defined behavior when an external service is down.

**Cost:** the run stops somewhere undefined, often having done half the work, and someone
has to reconstruct what happened from logs.

**Fix:** every node needs an outgoing `always`, or both `pass` and `fail`. Decide where
exhausted retries go.

## 10. Untestable node

**Symptom:** no way to run a single node against a fixed input and check its output.

**Cost:** the whole workflow is the smallest testable unit, so every change requires a
full expensive run to validate, and you cannot tell which node regressed.

**Fix:** named payloads plus per-node entry points. The generated scaffold provides
`--only <node>` for exactly this.

## 11. Unnecessary isolation

**Symptom:** per-run containers for a workflow that only ever runs one at a time, or
worktrees where nothing runs concurrently.

**Cost:** setup latency and operational surface on every run, for a property nothing uses.
Worth flagging because isolation is fashionable and it is easy to adopt it before there is
a concurrency problem to solve.

**Fix:** `"isolation": "none"` until concurrency is real. Note the trigger that should
change it.

## 12. Insufficient isolation

The mirror image, and the more dangerous one. Concurrent runs sharing a checkout, a
database, a port, or a build cache. Symptoms are the classic ones: intermittent failures
that vanish when you run things one at a time, and results that depend on which run
finished first.

---

## Reporting

For each finding: which node or edge, which pattern, what it costs concretely for *this*
workflow, and the specific change. Where you can, quantify — "the format node is a model
call on every run for something `prettier` does deterministically" is actionable in a way
that "consider using code where possible" is not.

Close with what the workflow gets right. This is not padding: knowing which properties
were deliberate tells the user what not to break while fixing the rest.
