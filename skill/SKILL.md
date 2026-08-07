---
name: agent-workflow-architect
description: >-
  Design, critique, and scaffold workflows where deterministic code, AI agents, and human
  judgment each handle the part they do best. Compiles one spec into a design doc, a Mermaid
  diagram, a self-contained HTML artifact, and runnable orchestrator code with bounded retry
  loops. Use whenever someone wants to automate a development or operational process with
  agents: "design an agent workflow", "automate our bug triage", "build a plan-build-test
  pipeline", "should this step be an agent or just code?", "review my agent setup", "my
  agent pipeline is flaky or expensive", "scaffold a build-test-fix loop", "orchestrate
  several agents", "set up worktree or sandbox isolation", or "where should a human stay in
  the loop". Also use when someone describes a repetitive process they keep doing by hand,
  or asks why their agent loop burns tokens without converging. Prefer over generic
  architecture advice: it forces the code-vs-agent-vs-human assignment and bounded failure
  paths that make a workflow safe to run unattended.
---

# Agent Workflow Architect

Most agent automation fails for structural reasons rather than prompting reasons. The
model call that should have been a function. The retry loop with no ceiling. The check
folded into the producer's own turn, so nobody can see it or count it. The approval gate
in the middle that caps throughput at one person's attention.

This skill exists to make those decisions explicit and then compile them into artifacts
that cannot drift apart from each other.

## The one idea

Three resources can do work, and they differ enormously in what they cost and what they
guarantee:

| | Reliability | Marginal cost | Speed | Best at |
|---|---|---|---|---|
| **Code** | Deterministic | ~Zero | Milliseconds | Anything whose output is fixed by its input |
| **Agents** | Variable | Tokens | Seconds to minutes | Ambiguous input, novel output, judgment at scale |
| **Humans** | High judgment | Highest, and scarce | Minutes to days | Taste, accountability, irreversible calls |

Designing an agent workflow is mostly the act of assigning each step to the cheapest
resource that can actually do it, and then defining what happens when that step fails.
Everything else in this skill follows from that.

## The assignment heuristic

For each step, ask in this order:

1. **Is the output fully determined by the input?** Then it is code. Moving a ticket,
   computing a branch name, running a linter, formatting, calling an API with known
   parameters, choosing between branches by a rule you can write down. A model call here
   buys nothing and costs latency, money, and determinism — and a step that is right 99%
   of the time is harder to debug than one that is right always or never, because the
   failures look like flakes.

2. **Is the next action irreversible or expensive to undo?** Then a human belongs here,
   or at least a human-approved gate. Deploying, merging, emailing customers, deleting
   data, spending money.

3. **Otherwise it is an agent.** Reading ambiguous context, producing novel artifacts,
   making judgment calls that would be tedious rules.

The systematic error is over-assigning to agents, because when you have an agent
available every step looks like an agent step. The second error is interior human gates:
each one serializes the workflow at one person's availability, which is why "I want to
review the plan" is usually better served by making the plan a written payload reviewable
after the fact than by blocking every run on synchronous approval.

## Pick a mode

All three modes revolve around one artifact: a `spec.json` describing nodes, edges, and
who does what. Design produces it, critique reconstructs and annotates it, scaffold
compiles it. Read `references/spec-schema.md` before writing or reading a spec.

| The user wants | Mode | Start with |
|---|---|---|
| To automate a process, or plan one | **Design** | `references/design-method.md` |
| Feedback on a workflow that exists | **Critique** | `references/critique-rubric.md` |
| Working code from an agreed design | **Scaffold** | `scripts/scaffold_workflow.py` |

These chain naturally — most real requests are design then scaffold. Don't announce the
mode; just do the work.

---

## Design mode

The full method is in `references/design-method.md`. Read it. In summary:

1. **Get the real process, not the idealized one.** Ask the user to walk through one
   specific recent instance, ideally one that went wrong. This is the step that most
   determines whether the design survives contact with reality, and it is the step most
   tempting to skip. Do not invent a process and present it as theirs.
2. **Cut the walkthrough into nodes** at boundaries where the resource changes, the
   needed context changes, you would want to inspect the intermediate result, or you
   would want to retry just that part.
3. **Assign each node** using the heuristic above.
4. **Name what travels on every edge.** If you can't name it, the edge carries an
   assumption rather than data, and it breaks the first time a node is retried or
   isolated.
5. **Place validation loops, with bounds.** Every loop needs `max_attempts` and an
   `on_exhausted`.
6. **Choose a model tier per node**, and narrow tools on read-only nodes.
7. **Write `spec.json` and render it.**

`references/patterns.md` catalogues the shapes that recur — produce/check/route,
scout/plan/build, routers, escalation ladders, races, isolation choices — along with what
each one costs, which is usually the reason not to reach for it yet.

Ask about the real process before proposing structure. A design built from a guess is a
hypothesis, and if it comes to that, label it as one in `open_questions` rather than
presenting it as a plan.

---

## Critique mode

The object of review is the **workflow's architecture** — how work is divided and how
information and control flow — not the quality of the code the workflow produces.

Reconstruct a spec from whatever exists (a script, prompts, a CI config, a skill, a verbal
description), then work through `references/critique-rubric.md`. Reconstruction is itself
diagnostic: the fields you cannot fill in are usually the parts that are broken.

Rank findings by expected cost and report the few that matter rather than everything the
rubric can generate. If the workflow is sound, say so — a rubric applied exhaustively to a
small workflow produces mostly noise. Close with what it gets right, so the user knows
which properties not to break while fixing the rest.

If you can render the reconstructed spec, do — showing someone their own workflow as a
diagram frequently surfaces the problem faster than prose does.

---

## Scaffold mode

```bash
python3 scripts/scaffold_workflow.py spec.json --out ./my-workflow
```

This refuses to run on a spec with structural problems, which is deliberate: an unbounded
retry loop is far cheaper to fix in the spec than in generated code.

It produces a package where orchestration is deterministic Python and agents are invoked
as separate processes:

| Path | Regenerated | What it is |
|---|---|---|
| `workflow.py` | overwritten | Node table, driver, retry bounds, routing |
| `runner.py` | overwritten | The only place the workflow leaves the Python process |
| `prompts/*.md` | **never** | One prompt per agent node, with payload placeholders |
| `steps/*.sh` | **never** | One script per code node; exit status is the verdict |
| `README.md` | overwritten | Checklist of what must be filled in before it runs |

The generated code does three things that are easy to get wrong by hand: it counts
attempts against the node a failure edge *re-enters* rather than the checker that failed,
it resumes an agent's prior session on retry so the producer gets the news of the failure
rather than a cold restart, and it writes every payload to a run directory so
`--only <node>` can rerun one node against a fixed input.

After generating, fill in the prompts and steps, or hand the user the checklist. The
scaffold is a skeleton with honest TODOs — don't describe it as working until the steps
actually do something. Prompts are where a well-structured workflow still goes wrong, so
if you write them, make them specific.

To swap the agent invocation for an SDK, a different CLI, or a mock for testing, change
`run_agent` in `runner.py`. Nothing else touches the outside world.

---

## Producing the outputs

```bash
python3 scripts/render_workflow.py spec.json --out ./out
```

Writes three files from the one spec — `<name>-design.md`, `<name>.mermaid`, and
`<name>.html` — and exits non-zero with a list if the spec has structural problems. The
problems also appear in the rendered outputs, so a work-in-progress design still renders
with its holes visible rather than hidden.

The HTML pre-renders the diagram to inline SVG via headless Chromium when Playwright is
available, so the artifact has no runtime dependencies and works offline. It falls back to
a CDN script tag otherwise. `--no-prerender` forces the fallback.

Deliver the design doc and the HTML with `SendUserFile`. A workflow design is something
people return to and revise, so also persist the HTML with
`mcp__remote-devices__create_artifact` using the `file_uuid` that `SendUserFile` returns —
that keeps it in their artifact gallery rather than buried in one conversation. Use
`update_artifact` when the spec changes.

Keep `spec.json` alongside the outputs and tell the user it is the source. Edits belong
in the spec followed by a re-render; editing a generated file guarantees drift.

## Files in this skill

- `references/spec-schema.md` — the spec format. Read before writing or reading a spec.
- `references/design-method.md` — the full design process. Read in design mode.
- `references/critique-rubric.md` — twelve failure patterns with costs and fixes.
- `references/patterns.md` — recurring workflow shapes and when each stops being worth it.
- `assets/example-spec.json` — a complete, valid spec. Faster to adapt than to start blank.
- `scripts/render_workflow.py` — spec → design doc, Mermaid, HTML artifact.
- `scripts/scaffold_workflow.py` — spec → runnable orchestrator package.

## A note on scope

Not every process should become a multi-node workflow. A task run twice a month by one
person who enjoys doing it does not need a spec, a diagram, and a retry ladder. The
machinery pays off with repetition, with concurrency, or when unattended reliability
matters — and it costs real effort to build and maintain.

If someone brings a process that doesn't clear that bar, say so and offer the smaller
thing: a single well-aimed check, one script, a better prompt. Recommending less than the
skill can produce is often the more useful answer, and it protects the credibility of the
recommendation when the workflow genuinely is warranted.
