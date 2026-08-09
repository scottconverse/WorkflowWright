# 0002 — Note the MCP Tasks correspondence, adopt nothing yet

**Status:** Accepted, 2026-08-09
**Deciders:** Scott Converse, with the WorkflowWright maintainers

## Context

The Model Context Protocol revision dated 2026-07-28 promotes **Tasks** to a first
class primitive: a caller starts work, receives a handle, and polls or is notified
until the work completes. The core protocol is stated as stateless, with an
extensions framework layered on top.

Delegate mode, added here in `c0bb050`, has the same shape and was arrived at
independently. A generated workflow reaches an agent node, writes the composed prompt
to `<run-dir>/<node>.prompt.md`, exits 76, and resumes when `<node>.result.md` appears
beside it. Driver position, attempt counts, and budget spend persist to
`driver-state.json` so the pause survives process death.

The correspondence is close enough to be worth writing down:

| Delegate mode | MCP Tasks |
|---|---|
| Exit 76 with a prompt file written | Start work, return a handle |
| `<node>.prompt.md` | The task's input |
| Polling for `<node>.result.md` | Poll the handle |
| `<node>.result.consumed.md` after use | Terminal state, not re-consumable |
| `driver-state.json` across the pause | Task state held outside the caller |
| Exit codes 75 and 76 | Distinct waiting-on-human vs waiting-on-agent states |

Two things fall out of that. The convergence is mild evidence the shape is right:
park/handle/resume is what long-running work looks like when the caller cannot hold
the context. And an eventual adapter — a generated workflow exposing its agent nodes
as MCP tasks, or consuming them — would be a translation rather than a redesign.

## Decision

**Record the correspondence. Adopt nothing. Write no adapter, take no dependency,
and change no field in the spec.**

Three reasons, in order of weight.

**The specification is days old.** It carries migration guidance, which means the
shape is still moving. Building against a revision at this age buys a rewrite.

**Nothing is currently blocked by its absence.** Delegate mode already works in every
host this project targets, precisely because it needs nothing from the host but a
filesystem. An MCP adapter would add a second way to do a thing that already works,
and second ways are where inconsistency lives.

**A file on disk is a better substrate for this than a protocol.** The whole reason
delegate mode is auditable is that its intermediate states are ordinary files a person
can read, diff, and keep. A protocol handle is not, and adopting one for its own sake
would trade the property the feature exists to provide.

## Consequences

The mapping table above is the deliverable. If an adapter is ever wanted, the work is
to translate between two things that already agree, not to redesign either.

Revisit when both of these hold:

- The Tasks primitive has been stable across at least two protocol revisions.
- Somebody actually wants a generated workflow driven by an MCP client, rather than by
  a person or a CLI — that is, the demand exists rather than being anticipated.

Until then this record exists so the question is answered once, and so nobody reads
the resemblance as an implicit roadmap item.

See also [0001](./0001-loopx-compile-target-deferred.md), which reached the same
conclusion about a different overlap, for the same underlying reason: shared shape is
not a reason to take a dependency.
