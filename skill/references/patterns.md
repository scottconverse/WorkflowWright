# Workflow patterns

A catalogue of shapes that recur. Read this when you need a starting structure or when a
design feels like it's missing something. These compose — most real workflows are two or
three of them nested.

Each pattern lists what it costs, because the cost is usually why someone shouldn't use it
yet.

---

## Produce → Check → Route

The atom. Everything else is built from it.

```
build ──always──> verify ──pass──> next
                     │
                     └──fail──> build   (loop, resumes session)
```

A producing node, a separate checking node, and a failure edge carrying the check's output
back. The check is deterministic code wherever possible — tests, lint, typecheck, schema
validation, a build succeeding. Deterministic checks are the highest-leverage thing in any
agent workflow because they convert "the model thinks it's done" into a fact.

**Requires:** `max_attempts` and `on_exhausted` on the producer.
**Cost:** one extra process invocation per attempt. Negligible.
**Use when:** always. If a workflow has no check node, that is the first thing to fix.

---

## Scout → Plan → Build

Splitting "figure out what to change" from "decide how" from "do it".

```
scout ──always──> plan ──always──> build
```

Scouting is retrieval: find the relevant files, prior art, related tickets, existing
conventions. Planning is judgment: decide the approach and write it down. Building is
execution against a written plan.

The split pays for itself three ways. Scout can run read-only, which is both cheaper and
safer. Plan produces a reviewable artifact, which is what lets you remove a synchronous
human approval gate without flying blind. And build starts from a plan rather than from a
blank context, so its prompt is short and specific.

Scouting is the stage people most want to parallelize, and the one that punishes it
hardest — see "Do not split understanding across nodes that cannot talk" in
`design-method.md`. Keep it one node and give it the strongest tier; if a single pass is
not enough, chain a second scout that reads the first's report rather than adding a
sibling that cannot see it.

**Cost:** two extra model calls, and latency, since these are inherently sequential.
**Use when:** the work requires understanding an existing codebase. Skip it for
self-contained mechanical tasks where there is nothing to scout.

---

## Router

One classification step that dispatches to different downstream workflows.

```
intake ──always──> classify ──> chore-flow
                            ├──> bug-flow
                            └──> feature-flow
```

The point is that different work deserves different amounts of machinery. Running a
five-node scout/plan/build/verify/review pipeline on a dependency bump is pure waste;
running a single cheap agent on a subtle production bug is negligent. A router lets one
entry point serve both without compromising on either.

The classifier is often the cheapest agent in the whole system, or sometimes not an agent
at all — a label on the ticket may already carry the answer, in which case this is a
`code` node.

When it does need a model, this is the best candidate in the entire graph for a
self-hosted one: routing is classification, classification is the narrow shape of work
small models are measurably good at, and the dispatch then costs nothing so the whole
budget goes to the work. Set `"backend": "openai-compat"` with an `endpoint`.

One caveat that does not apply to the other nodes you would route locally. A bad
summary announces itself; a bad route does not. Sending a subtle production bug down
the chore path does not fail, it just quietly under-serves. So review a classifier's
split across a sample of real items before trusting it, rather than checking outputs
one at a time.

**Cost:** a classification step, plus the real cost, which is maintaining N downstream
workflows instead of one.
**Use when:** you have at least two genuinely different kinds of work and the cheap kind
is frequent. Not before.

---

## Escalation ladder

Try cheap, then expensive, then a human.

```
build (haiku, 2 attempts) ──exhausted──> build (opus, 1 attempt) ──exhausted──> human
```

This is the response to the observation that most tasks are easy and a few are not, and
you cannot tell which is which in advance. Paying the strong-model price on every run to
cover the hard 10% is a common and expensive default.

The ladder only works when failure is detectable — it depends on a deterministic check
telling you the cheap attempt didn't work. Without that, you are just running the cheap
model and hoping.

**Cost:** worst-case latency is the sum of all rungs, so a task that fails all the way up
takes much longer than it would have on the strong model directly.
**Use when:** volume is high, the check is trustworthy, and the cheap model succeeds often
enough to pay for the failures. Measure before assuming.

---

## Race

N isolated attempts in parallel; first one to pass the check wins, the rest are killed.

```
        ┌──> attempt-1 (sandbox) ──┐
fix ────┼──> attempt-2 (sandbox) ──┼──> first passing wins ──> ship
        └──> attempt-3 (sandbox) ──┘
```

Trades money for latency, directly and unapologetically. It is the right trade in a narrow
band of situations: production is down, the cost of another minute exceeds the cost of
three redundant runs, and there is a fast automated check that can declare a winner.

Requires real isolation — attempts must not share a checkout, a database, or a port, or
they will corrupt each other and you will get a "winner" that only passed because of
another attempt's side effects.

**Cost:** N times the tokens, N times the sandbox setup, and meaningful orchestration
complexity around cancellation and cleanup.
**Use when:** latency is genuinely the binding constraint. Almost never otherwise.

---

## Isolation

Give each concurrent run its own filesystem.

**Worktrees** (`git worktree add`) are cheap, start in under a second, and share the
object store. They isolate the checkout and nothing else — concurrent runs still share the
dependency cache, the host's ports, any database, and the ability to damage the machine.

**Sandboxes** (container or VM per run) isolate everything, survive a destructive agent,
and let a person attach to a running attempt to see what it is doing. They cost startup
time and infrastructure.

The useful decision rule: worktrees until a run can break something outside its own
checkout, then sandboxes. Concretely, that means sandboxes once runs install dependencies,
bind ports, touch shared services, or execute code you would not run on your laptop.

**Cost:** setup latency per run, plus cleanup you have to actually implement — abandoned
worktrees and orphaned containers accumulate silently.
**Use when:** runs are concurrent. Not before; see finding #11 in the critique rubric.

---

## Human at the ends

Not a shape so much as a placement rule, but worth stating as a pattern because it is the
one that determines throughput.

People belong at **intake** (deciding what should be done, and to what standard) and at
**acceptance** (deciding whether what came out is good enough), plus any interior node
whose next action is irreversible or expensive to undo.

The reason to be strict about the interior is arithmetic. A workflow with one synchronous
human gate in the middle can only run as many times per day as that person can attend to
it, no matter how many agents you point at it. Moving the review to the end changes the
person's job from "unblock each run as it arrives" to "review a queue of finished work",
which batches, which is what makes throughput scale.

The escape valve when someone is uncomfortable removing an interior gate: make the thing
they wanted to approve into a written payload, and let them read it after the fact for
the first few dozen runs. If it never surprises them, the gate was unnecessary. If it does,
they now have concrete evidence about which node needs work.
