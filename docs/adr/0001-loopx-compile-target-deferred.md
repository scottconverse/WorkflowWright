# 0001 — Borrow LoopX's primitives, defer LoopX as a compile target

**Status:** Accepted, 2026-08-08
**Deciders:** Scott Converse, with the WorkflowWright maintainers

## Context

[LoopX](https://github.com/huangruiteng/loopx) (evaluated at v0.4.x) is a run-time
state kernel for long agent loops. It provides durable goals, human gates, claimable
todos with leases, evidence logs, quota scheduling, and local state under `.loopx/`.

The overlap with WorkflowWright is real and not superficial. Both are answers to the
same underlying complaint: an agent loop with no durable state outside the model's
context will retry forever, lose track of what it already did, and give no one a way
to see what happened. Several of LoopX's primitives are things this project either
already had, or wanted.

That overlap raised a genuine question rather than a rhetorical one. If LoopX already
implements the state kernel, should WorkflowWright stop implementing its own and
compile *to* LoopX instead — emitting a LoopX configuration rather than a Python
orchestrator?

The evaluation was done outside this repository, against LoopX itself. This record
exists so the question is answered once rather than reopened from scratch.

## Decision

**Borrow the primitives as spec features. Take no dependency on LoopX. Write no
emitter and no importer.**

Three reasons, in the order they mattered.

**The stdlib-only property is load-bearing, not incidental.** WorkflowWright runs
anywhere Python 3.10 runs, with nothing installed. That is what makes it usable inside
an assistant session, on a locked-down machine, in a container with no network, and in
a CI job that installs nothing. A dependency on an external kernel — any external
kernel — trades that for capability the project does not currently need. The test
suite's own guarantee, that it runs with no network, no credentials, and no token
spend, comes from the same property.

**The scaffold already carries a run-state layer.** By the time this question was
asked, the generated driver already persisted its position, attempt counts, pending
feedback, and budget spend to a run directory, and already parked and resumed across
process death. Adopting an external kernel would mean replacing a working layer that
fits the data model exactly, and the replacement's obligations — leases, claim
protocols, a scheduler — are obligations this project does not have.

**A run is not a campaign.** This is the deepest reason. WorkflowWright describes a
*bounded DAG*: it starts, traverses nodes, and terminates. Its ceilings exist so a run
provably stops. LoopX addresses *multi-day goals*, where work is claimed by whoever is
free, leases expire, and progress accumulates against an objective that outlives any
single run. Those are different problems. Mapping one onto the other would blur the
property this project most depends on — that a run ends.

## What maps to what

Recorded now, while the correspondence is fresh, so that a future emitter would not
start from a blank page:

| WorkflowWright | LoopX | Notes |
|---|---|---|
| Node | Todo | A WorkflowWright node is statically declared; a LoopX todo is claimable at run time. The static form is a subset. |
| `kind: human` node | User gate | Closest correspondence of the set. Both stop the machine and wait for a person. |
| Edge `payload` | Evidence entry | Both name an artifact travelling between steps rather than assuming shared memory. |
| Node `evidence` | Evidence log entry | WorkflowWright checks existence and non-emptiness at the gate; LoopX accumulates entries. |
| `max_attempts` + `budget.agent_calls` | Quota policy | Per-node and per-run ceilings versus a scheduler's quota. Similar intent, different enforcement point. |
| `driver-state.json` | `.loopx/` state | Both are durable run state on local disk. |
| Bounded DAG with a terminal node | Durable goal | **No clean mapping.** A goal does not terminate the way a run does; this is the gap that makes an emitter more than a translation. |

## Consequences

Accepted costs. WorkflowWright will reimplement things LoopX already solved, and will
keep doing so as its run-state needs grow. If LoopX becomes widely adopted, workflows
described here will not interoperate with it without manual translation. Concurrency
across runs remains out of scope: `isolation` records intent but the scaffold does not
implement it, and nothing here claims a scheduler.

Accepted benefits. The install story stays "clone it, or copy one directory." The
tests keep running offline with no credentials. And the failure modes stay inside one
readable Python file rather than spanning a process boundary into another project's
state machine.

## When to revisit

Two conditions, and **both** must hold:

1. Scott adopts LoopX in daily use, so the emitter would serve real work rather than a
   hypothesis.
2. LoopX's on-disk formats stabilise, so an emitter would not be rewritten against a
   moving target.

Until both are true: **no emitter, no importer, no dependency.** If they become true,
start from the mapping table above and treat the goal-versus-run mismatch as the
design problem to solve first, because it is the only row with no answer.
