# Design method

Read this when running design mode. It expands the seven steps summarized in SKILL.md.

## Step 1 — Get the real process, not the idealized one

The single biggest determinant of whether a designed workflow survives contact with
reality is whether it was designed from what actually happens or from what people say
happens. These diverge more than anyone expects. The idealized version has five clean
steps; the real version has five steps plus a Slack message to the one person who knows
why the staging migration is different, plus a manual retry that everybody does and
nobody documents.

So before proposing any structure, get the user to walk one recent real instance end to
end. Not the general shape — one specific case, ideally the most recent one, ideally one
that went slightly wrong. Ask what they actually typed, what they read, what they waited
on, where they had to make a judgment call, and where they went back and redid something.

Useful prompts:

- "Take me through the last time you did this. Start from the moment you knew it needed
  doing."
- "Where did you stop and think, versus where were you just typing something you'd typed
  before?"
- "What did you have to go find? Where did you find it?"
- "What went wrong the last time this went wrong?"

That last question is the highest-yield one, because failure paths are where workflows are
won or lost and they are almost never volunteered.

If the user genuinely cannot describe the process because it does not exist yet, that is
fine — but say so explicitly in the design doc's open questions, because a workflow
designed from an imagined process should be treated as a hypothesis, not a plan.

## Step 2 — Cut the walkthrough into nodes

A node boundary belongs wherever one of these changes:

- **The resource changes.** A person stops deciding and a script starts running.
- **The context changes.** The work stops needing the ticket and starts needing the test
  output. Carrying context a node doesn't need is how prompts bloat and models get
  distracted.
- **You would want to see what happened.** If you'd want to inspect the intermediate
  result when debugging, it needs to be a real boundary with a real payload, not something
  that happens inside another step.
- **You would want to retry just that part.** Retry granularity is node granularity. If
  the whole thing is one node, your only recovery option is to redo everything.

The last two are the ones people skip, and skipping them produces the single-monolithic-
agent design that is so hard to debug later.

Resist the opposite error too. A node per shell command is not insight, it's bookkeeping.
If two adjacent steps use the same resource, need the same context, always succeed or fail
together, and you'd never inspect between them, they're one node.

### Do not split understanding across nodes that cannot talk

Every cut above is a cut in *sequence* — one node finishes, hands a payload forward, and
the next begins. A different instinct arrives at the same moment and looks like the same
move: splitting one stage *sideways*, across several agents working at once. Three scouts,
one per subsystem, and a node that merges their reports.

That is the split to refuse, and the reason is measured rather than aesthetic. On
enterprise codebase tasks, four agents that could share findings while still working
scored 62.1%; a single strong agent working alone scored 57.2%; the same compute spent on
independent parallel agents that could not share scored **37.9%**. Partitioning the work
was not merely less good than coordinating — it was far worse than not partitioning at
all.

The reason is that understanding a codebase does not decompose along the lines you would
partition it on. The fact that the auth scout needs is the one the billing scout found:
the shared abstraction that explains why both subsystems are strange in the same way.
Working blind to each other, each one rediscovers the same context, and each one misses
the part the other holds. You pay three times for less than one agent's worth of
understanding.

This matters here specifically, because **a spec has no channel between nodes running at
the same time.** Every edge carries a payload from a *finished* node to a *starting* one.
So the fan-out-and-merge design is exactly the configuration that scored 37.9% — the spec
language can express it, and you should not.

What to do instead:

- **One scout node**, strongest tier, read-only tools. Sequential and unglamorous.
- **If one pass isn't enough, chain rather than fan out.** A second scout node that reads
  the first's report is still sharing discoveries; it has just serialized the sharing into
  something an edge can carry. Slower than parallel, and it actually works.
- **Push the parallelism into the node, not the graph.** If the host running an agent node
  can spawn its own helpers that talk to each other, that is coordination and it is fine.
  What fails is a graph whose siblings are mutually deaf.

The exception is Race (see `patterns.md`), and it is instructive: racing runs parallel
attempts that are *redundant* rather than *partitioned*. Each attempt does the whole task,
so there is nothing to share, because nothing was divided. Parallelism is safe exactly
when no agent needs what another one learned.

## Step 3 — Assign each node

Apply the heuristic in SKILL.md. Two notes on doing it honestly:

**Bias toward code harder than feels natural.** When you have an agent available, every
step looks like an agent step. But a step whose output is fully determined by its input
is a function, and running it through a model buys you nothing while costing latency,
money, and determinism. "Move the ticket to In Progress" is an API call. "Decide whether
this ticket is a bug or a feature" is a model call. The line is whether the step requires
reading ambiguous input and producing a judgment.

**Be suspicious of human nodes in the interior.** Each one is a place where the workflow
stops until a specific person is available, which caps throughput at that person's
attention regardless of how much compute you throw at everything else. Interior human
nodes earn their place when the next action is irreversible or expensive to undo —
deploying, sending mail to customers, deleting data, spending money. "I want to check the
plan looks right" is a real desire, but it is usually better served by making the plan a
written payload you can review after the fact than by blocking the run on synchronous
approval.

**Assign the meter too, not just the resource.** Deciding a step is agent work leaves
a second question open: which system runs it, and whose bill it lands on. No single
agent system reaches every model, so this is about capability as much as cost —
Antigravity is the only route to Gemini and to Claude on a meter separate from your
Claude quota, Codex is the only route to the GPT-5.x fleet, and a self-hosted server
is the only one that costs nothing at all. A workable default:

- **Mechanical, high-volume, checkable** — classification, tagging, format
  conversion, first-draft commit messages — goes to a self-hosted model. It is free,
  and a small model is genuinely good at this narrow shape of work.
- **Judgment that something downstream will check** — building, drafting, routine
  code changes — goes to a mid tier, or to Codex if you would rather spend that
  account than your Claude one.
- **Judgment nothing downstream can check** — scouting, planning, final review,
  anything security-sensitive — stays on the strongest tier available.

Record it as `backend` on the node, with `endpoint` when it is a self-hosted server.
Two constraints the validator will hold you to, both worth understanding rather than
working around: a self-hosted node's output must be reachable by a `fail` edge from
something that can reject it, because a small model's output is raw material rather
than a result; and a self-hosted endpoint is only private while its address is
loopback. Point one at another machine and the payload leaves this one, exactly as it
would for a cloud API. The design doc names the destination for every agent node so
that stays visible.

## Step 4 — Name what travels on every edge

For each edge, answer: what does the downstream node need, in what form, and where does it
live? Write it down as the `payload`. If you cannot name it, the edge is carrying an
assumption rather than data, and it will break the first time a node is retried or run in
isolation. See the "Why payloads are named" section of `spec-schema.md`.

## Step 5 — Place validation loops, with bounds

A validation loop is three things: a producing node, a checking node, and a failure edge
that carries the check's output back to the producer.

The critical structural rule is that the check must be a separate node from the producer.
It is tempting to tell the building agent "when you're done, run the tests and fix
anything that fails" — one node, less plumbing. But that collapses four capabilities:

- **Observability.** When the check runs inside the agent's turn, its output is buried in
  a transcript instead of being a payload you can read, log, and diff across runs.
- **Bounded retry.** You cannot cap attempts you cannot count. Inside a turn, an agent may
  loop three times or eleven, and you find out from the bill.
- **Routing.** A separate check lets failure go somewhere other than back to the producer
  — to a stronger model, to a human, to a different specialist node.
- **Independent substitution.** Separate nodes can be swapped independently. You can move
  the builder to a cheaper model without touching verification, or add a second check
  without renegotiating the builder's prompt.

Every loop needs `max_attempts` and an `on_exhausted`. An unbounded retry loop against a
paid API is the one design error in this whole document that can cost real money while
you sleep.

When a failure edge routes back into an agent node, the retry should resume that agent's
prior session rather than starting cold. The producer already has the context of what it
was trying to do; what it lacks is the news that it failed and why. Starting fresh throws
away the former to deliver the latter. The scaffold does this automatically for edges
marked `"loop": true`.

## Step 6 — Choose model tiers per node

Uniform model selection is a smell in both directions. The nodes where a weak model is
most expensive are the ones that decide what happens next: scouting (missing a relevant
file poisons everything downstream) and planning (a bad plan gets faithfully implemented).
The nodes where a strong model is most wasted are mechanical: applying a known edit,
summarizing a diff, formatting output.

A reasonable default: strongest tier for scout and plan, mid tier for build, cheapest tier
that can do the job for mechanical transforms, and no model at all wherever step 3 said
"code".

Also narrow `tools` per agent node. A scout that only has read tools cannot accidentally
edit; that is both a cost control and a safety property, and it makes the node's behavior
much easier to reason about.

## Step 7 — Write the spec and render it

Write `spec.json` per `spec-schema.md`, then:

```bash
python3 scripts/render_workflow.py spec.json --out ./out
```

This produces the design doc, the Mermaid source, and the HTML artifact together, so they
cannot disagree with each other.

## What "done" looks like

A design is ready to hand over when someone who was not in the conversation could read the
design doc and answer: what starts this, what does each step do and who does it, what
happens when each step fails, where does a human get involved, and how would I test one
step in isolation. If any of those is unanswerable, the gap belongs in `open_questions`
rather than being papered over — an explicit unknown is a working design with a hole in
it, while an implicit one is a design that will fail without telling you why.
