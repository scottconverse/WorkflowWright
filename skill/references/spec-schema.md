# Workflow spec schema

Every mode of this skill reads or writes a single JSON file, conventionally `spec.json`.
Design mode produces it. Critique mode reconstructs it from an existing setup and annotates
it. Scaffold mode compiles it into runnable code. Keeping one representation means the
diagram, the design doc, and the code can never drift from each other — they are all
generated from the same source.

## Top level

```json
{
  "name": "feature-delivery",
  "goal": "Take an accepted ticket to a reviewed pull request",
  "trigger": "A ticket moves to Ready in the tracker",
  "isolation": "worktree",
  "entry": "intake",
  "nodes": [ ... ],
  "edges": [ ... ],
  "open_questions": [ "..." ]
}
```

| Field | Required | Notes |
|---|---|---|
| `name` | yes | Lowercase, hyphenated. Used for output filenames and the scaffold package name. |
| `goal` | yes | One sentence. What comes out the far end. |
| `trigger` | yes | What starts a run. Be specific — "a ticket moves to Ready", not "when work is needed". |
| `isolation` | yes | `worktree`, `sandbox`, or `none`. See below. |
| `entry` | yes | `id` of the first node. |
| `nodes` | yes | Array of node objects. |
| `edges` | yes | Array of edge objects. |
| `open_questions` | no | Things the design can't settle without the user. Surfaced in every output. |

`isolation` values:

- `worktree` — each concurrent run gets its own `git worktree`. Cheap, fast, shares the
  object store. Breaks down when runs need different dependency versions, when build
  artifacts collide outside the tree, or when a run can damage the host.
- `sandbox` — each run gets its own container or VM. Full isolation, survives destructive
  agents, lets a human attach and inspect a running attempt. Slower to start, costs more.
- `none` — runs are serialized against one checkout. Fine to start with, and the honest
  choice for a workflow that is only ever run one at a time.

## Node objects

A node is one unit of work performed by exactly one of three resources. The `kind` field
is the whole point of the exercise — see the assignment heuristic in SKILL.md.

```json
{
  "id": "verify",
  "label": "Run tests, lint, and typecheck",
  "kind": "code",
  "detail": "make verify — exits non-zero on any failure, writes verify-report.txt",
  "reads": ["worktree"],
  "writes": ["verify-report.txt"],
  "max_attempts": 1,
  "on_exhausted": "fail"
}
```

| Field | Required | Applies to | Notes |
|---|---|---|---|
| `id` | yes | all | Short, snake_case, unique. Becomes a function name in the scaffold. |
| `label` | yes | all | Human-readable, shown in the diagram. |
| `kind` | yes | all | `code`, `agent`, or `human`. |
| `detail` | yes | all | For `code`, the actual command. For `agent`, the job in one or two sentences. For `human`, what the person is deciding. |
| `model` | no | agent | `haiku`, `sonnet`, `opus`, `fable`, or a full model name. Omit to inherit the default. |
| `tools` | no | agent | Allowed tool list, e.g. `["Read","Grep","Glob"]`. Narrow tools on read-only nodes is a real safety and cost win. |
| `reads` | no | all | Named payloads this node consumes. |
| `writes` | no | all | Named payloads this node produces. |
| `max_attempts` | no | all | Retry bound. Defaults to 1. Any node that a `fail` edge loops back into needs a real number here. |
| `on_exhausted` | no | all | `fail`, `human`, or `escalate-model`. What happens when `max_attempts` is used up. Defaults to `fail`. |

`on_exhausted` values:

- `fail` — stop the run, non-zero exit. Right for workflows a person is watching.
- `human` — pause and hand the accumulated context to a person. Right for anything running
  unattended, because a silent failure at 3am is worse than a paged human.
- `escalate-model` — retry once more on a stronger model before giving up. Worth it when
  the failure mode is "the cheap model couldn't figure it out" rather than
  "the task is impossible". Costs money; don't reach for it by default.

## Edge objects

```json
{ "from": "verify", "to": "build", "when": "fail", "payload": "verify-report.txt", "loop": true }
```

| Field | Required | Notes |
|---|---|---|
| `from` | yes | Source node id. |
| `to` | yes | Target node id. |
| `when` | yes | `always`, `pass`, or `fail`. |
| `payload` | no | What travels along this edge. Name it explicitly — see below. |
| `loop` | no | `true` marks a backward edge. Drawn dashed; the scaffold resumes the target's prior session instead of starting fresh. |

Every node needs an outgoing `always`, or both a `pass` and a `fail`. A node with only a
`pass` edge is a bug: it means you have not decided what happens when that step fails, and
the run will simply stop there.

## Why payloads are named

The most common failure in a hand-built agent pipeline is an edge that carries nothing
explicit — the workflow assumes an agent still "remembers" something from three steps ago,
or that a file is sitting in the working directory because an earlier node happened to put
it there. That works until a node is retried, reordered, or moved into its own sandbox,
and then it fails in a way that is very hard to see.

Naming the payload on every edge forces the question "what does the next node actually
need, and where will it find it?" while the design is still cheap to change. In the
scaffold, payloads become real files in a run directory, which also means you can rerun a
single node against a fixed input when you are debugging.

## Worked example

`assets/example-spec.json` is a complete, valid spec for a ticket-to-pull-request workflow
with a bounded build/verify loop, a scout/plan split, and human touchpoints only at intake
and acceptance. Read it before writing a spec from scratch — it is faster than assembling
one field by field, and it demonstrates the conventions above.
