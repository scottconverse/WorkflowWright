# WorkflowWright manual

The reference for people the [README](../README.md) has already convinced. Organized
for lookup, not persuasion.

- [Concepts](#concepts)
- [Proving a node worked](#proving-a-node-worked)
- [The run budget](#the-run-budget)
- [Human gates and decision records](#human-gates-and-decision-records)
- [The three modes](#the-three-modes)
- [Writing a spec by hand](#writing-a-spec-by-hand)
- [Running a generated workflow](#running-a-generated-workflow)
- [Writing good prompts and steps](#writing-good-prompts-and-steps)
- [Platform notes: Windows](#platform-notes-windows)
- [Troubleshooting](#troubleshooting)
- [The traps](#the-traps)
- [Maintaining the landing page](#maintaining-the-landing-page)
- [Extending it](#extending-it)

## Concepts

A workflow is a directed graph in one JSON file, conventionally `spec.json`. The full
field reference lives in [`skill/references/spec-schema.md`](../skill/references/spec-schema.md)
— it is deliberately the only place the field tables exist, so this manual and the
schema cannot disagree. The shape in brief:

- **Nodes** do work. Each has a `kind`: `code` (deterministic — a shell script whose
  exit status is the verdict), `agent` (a model invocation — variable, costs tokens),
  or `human` (a decision only a person should make).
- **Edges** route control between nodes, conditioned on `always`, `pass`, or `fail`.
  Every edge names a `payload` — the artifact that actually travels. An edge that
  can't name its payload is carrying an assumption, and it breaks the first time a
  node is retried or rerun in isolation.
- **Retry bounds.** Any node that a `fail` edge re-enters is a retry target and must
  declare `max_attempts` and `on_exhausted` (`fail`, `human`, or `escalate-model`,
  which grants one final attempt on a stronger model). The validator refuses specs
  that omit these.
- **Evidence.** A node may name the artifact that proves it did its job. A node that
  reports success without producing it has failed, and routes accordingly. See
  [proving a node worked](#proving-a-node-worked).
- **Budget.** A top-level ceiling on agent calls for the whole run, closing the gap
  `max_attempts` cannot see across. See [the run budget](#the-run-budget).
- **Isolation** declares where runs execute: `none`, `worktree` (one git worktree per
  run — parallel runs can't trample each other), or `sandbox` (a container or VM per
  run — survives destructive mistakes). See the schema for the trade-offs. Note that
  this field is a **design decision the tooling records and reasons about, not one it
  implements**: the generated package prints the declared mode in its docs but never
  creates a worktree or a container. Creating and tearing down the isolated
  environment belongs in your entry node — the bundled example spec does it in
  `intake`.

## Proving a node worked

An exit code is a claim. A node can return zero having written nothing, and everything
downstream then proceeds on the assumption that it did something. `evidence` names the
artifact that settles it:

```json
{ "id": "verify", "kind": "code", "evidence": "verify-report.txt" }
```

A node that reports success must have left that file in the run directory, non-empty,
before any edge out of it is followed. If it did not, the node **failed** — it routes
down its `fail` edge, spends an attempt, and reaches `on_exhausted` exactly like any
other failure. Nothing about it is special-cased, which is the point: there is one
kind of failure and one set of rules for handling it.

It gates every successful traversal, including `always` edges. If it gated only `pass`
edges it would barely fire — the bundled example has five `always` edges to one `pass`.

**Be precise about what this buys you.** The bar is that the artifact exists and is not
empty. That catches the silent no-op, which is the failure that actually happens: the
step that reported success and produced nothing, whose absence is then discovered three
nodes later or not at all. It does **not** catch a node writing the word `done` to a
file to get past the check. If you want a real bar, put it in the checker node where it
belongs, and use evidence to guarantee the checker itself produced a report.

Because a missing artifact makes the node fail, a node with `evidence` needs a `fail`
edge. The validator refuses the spec otherwise, on the same grounds it refuses any node
whose failure has nowhere to go.

## The run budget

`max_attempts` bounds each node in isolation and cannot see across nodes. That leaves a
gap: a producer and a checker on a loop edge can each honour their own ceiling and still
ping-pong, spending indefinitely while every individual bound is respected and nothing
ever stops. A top-level budget closes it:

```json
{ "budget": { "agent_calls": 12 } }
```

Retries count. A call is charged when it returns, whatever the outcome — a call that
launched and then errored or timed out has already cost money, so crediting only
successes would let a crash-looping node spend while the counter stayed flat. Two things
are never charged: a missing agent CLI, which never launched, and a delegated park,
which exits the process before any model runs.

The count lives in `driver-state.json`, so it survives the pauses of delegate mode. An
in-memory counter would reset at every park and make the budget infinite in the mode most
likely to be watched by someone paying attention to cost.

Exhaustion is not a crash. The run stops between nodes, hands off through the recorded
gate below, and tells you what to raise.

## Human gates and decision records

Every `human` node writes `<node>.decision.json` when it is answered — the node id, what
was presented, the verdict, the reasoning, and a UTC timestamp. `on_exhausted: "human"`
and budget exhaustion record the same way, since they route through the same gate.

In delegate mode a human node parks like an agent node rather than requiring a terminal:
the question goes to `<node>.decision.md`, and you answer by writing `<node>.answer.md`
beside it. The first line is the verdict, `yes` or `no`, and everything after is kept as
your reasoning. **An answer that is neither is recorded as not approved** — an
unparseable answer is exactly where a person meant something specific, and reading
consent into it is the one wrong way to resolve the ambiguity.

This is what makes an approval gate reachable at all for anyone without a terminal.
Before it, the run parked and the only way onward was `--from`, which skips a gate
rather than answering it.

## The three modes

### Design

Design mode interviews you and writes the spec. The part users try to skip is the
part that matters most: it asks you to walk through **one specific recent instance**
of the process — ideally one that went wrong — rather than the idealized general
shape. Failure paths are where workflows are won, and nobody volunteers them; the
general shape you'd describe from memory has no failure paths in it. The highest
value question in the interview is "what went wrong the last time this went wrong."

From the walkthrough it cuts the process into nodes at the boundaries where the
resource changes, assigns each node to code, agent, or human, names every edge's
payload, bounds every loop, and hands back the spec plus its three rendered outputs.

### Critique

Critique mode reviews a workflow that already exists — a script, a pile of prompts, a
CI config, a verbal description. It reconstructs a spec from whatever you have, which
is itself diagnostic: the fields that can't be filled in are usually the parts that
are broken. The object of review is the **workflow's architecture** — how work is
divided and how information flows — not the quality of the code the workflow
produces. It reports the few findings that cost you something, ranked by expected
cost, not everything a rubric can generate.

### Scaffold

Scaffold mode compiles an agreed spec into a runnable package:

```sh
python3 skill/scripts/scaffold_workflow.py spec.json --out ./my-workflow
```

The generated package, file by file:

| File | Overwritten on regeneration? | Role |
|---|---|---|
| `workflow.py` | yes | The driver: node table, edge routing, retry accounting, `--only`/`--from` |
| `runner.py` | yes | Process boundaries: `run_agent`, `run_step`, `ask_human` — the only file that leaves Python |
| `spec.json` | yes (copied in) | The source of truth, kept with the package |
| `prompts/<node>.md` | **no** | One prompt template per agent node |
| `steps/<node>.sh` | **no** | One bash script per code node |
| `README.md` | yes | Checklist of what must be filled in before the workflow runs |
| `runs/` | created at run time | One directory of payload files per run |

Every generated step exits 1 with a TODO message until you fill it in. Regeneration
never touches `prompts/` or `steps/` unless you pass `--force`, so the generated
skeleton and your hand-written work can evolve separately.

## Writing a spec by hand

If you'd rather skip the interview, start from
[`skill/assets/example-spec.json`](../skill/assets/example-spec.json) — a complete
working example — and adapt it. Then render it; the validator runs automatically and
refuses to scaffold (and flags in rendered output) anything structurally broken.

What the validator catches, exactly:

- duplicate node ids; an `entry` that names no node
- a node `kind` outside `code` / `agent` / `human`; a `model` on a non-agent node
- edges whose `from`/`to` name no node; a `when` outside `always` / `pass` / `fail`
- edges with no `payload`
- a node with a `pass` edge but no `fail` edge (undefined behavior on failure), or
  the reverse (a success path that goes nowhere)
- no terminal node — every path loops forever
- a retry target with no `max_attempts`, a `max_attempts` below 1, or no
  `on_exhausted` — unbounded retries against a paid API are the one design error
  that costs real money unattended

This refusal is deliberate: an unbounded loop is far cheaper to fix in the spec than
in generated code that has already burned tokens discovering it.

## Running a generated workflow

```sh
python3 workflow.py                    # full run from the entry node
python3 workflow.py --delegate         # full run, but you do the agent nodes
python3 workflow.py --from verify      # start partway through
python3 workflow.py --only build       # run one node against the last run's payloads
python3 workflow.py --run-dir runs/7   # keep this run's payloads separate
python3 workflow.py --workdir ~/proj   # where steps and agents execute (default .)
```

`--only` is the reason payloads are files: you can rerun a single node against a
fixed input while debugging it, instead of replaying the whole workflow to reach it.

### Two ways to run agent nodes

The deterministic half of a workflow — routing, retry ceilings, payloads, which node
comes next — is identical either way, because it lives in the driver rather than at
the process boundary. Only the model call moves.

| | **Subprocess** (default) | **Delegate** (`--delegate`) |
|---|---|---|
| Agent nodes run by | an agent CLI, spawned per node | whoever is driving the workflow |
| Needs `claude` on PATH | yes | no |
| Runs unattended start to finish | yes | no: pauses at each agent node |
| Session resume on retry | yes, via `--resume` | n/a — you keep your own context |
| Suits | a terminal, CI, cron | working inside an assistant, or doing a node by hand |

Neither is the lesser path. Pick by where you work.

### The delegate loop

Use it when there is no terminal to run an unattended job from — for example when
you are working inside Claude Code, Cowork, or any assistant session. Rather than
spawning a nested agent that spends tokens out of sight, the run parks and asks the
session you are already in to do the node.

Each pause writes two paths and exits **76**:

```
=== scout is delegated ===
This node is specified for model opus, limited to tools: Read, Grep, Glob.
Prompt written to : run/scout.prompt.md
Write the answer to: run/scout.result.md
```

`scout.prompt.md` is the fully composed prompt with payloads already substituted and
authoring comments stripped — exactly what a model would have received. Do that work,
save the result to `scout.result.md`, and run the same command again with the same
`--run-dir`. The driver picks up where it left off.

Two details worth knowing. The answer file is **renamed to `.result.consumed.md`
rather than deleted**, so a retry cannot silently re-consume the reply to an earlier
attempt, and the run directory still reads as a transcript afterwards. And an **empty
answer counts as a failure**, routing down the node's fail edge rather than passing
nothing downstream.

Attempt counts and the retry ceiling survive the pause: the driver persists its
position to `driver-state.json` in the run directory before each node, and clears it
when the run finishes. So a bounded loop stays bounded no matter how many times the
process stops and starts, and a retried node's prompt still carries the checker's
feedback.

Environment variables, all optional:

| Variable | Default | Meaning |
|---|---|---|
| `WORKFLOW_AGENT_TIMEOUT` | `1800` | Seconds before an agent invocation is killed |
| `WORKFLOW_STEP_TIMEOUT` | `3600` | Seconds before a step script is killed |
| `WORKFLOW_PERMISSION_MODE` | `acceptEdits` | Passed to the agent CLI as `--permission-mode` |
| `WORKFLOW_AGENT_CLI` | `claude` | The agent command; may carry arguments (e.g. a test stub) |
| `WORKFLOW_DELEGATE` | unset | Set to `1` for delegate mode; same switch as `--delegate` |
| `WORKFLOW_BASH` | unset | Windows only: which bash runs step scripts |

Exit codes:

| Code | Meaning |
|---|---|
| `0` | The run reached a terminal node |
| `1` | A node failed with no fail edge, or exhausted its retries with `on_exhausted: fail` |
| `2` | Operator error — unknown node passed to `--only` |
| `75` | **Parked awaiting a human.** Not an error: a human node was reached unattended. Review the run directory, then continue with `--from <node>` |
| `76` | **Parked awaiting a delegated agent.** Write the answer file the message names, then run the same command again |

75 is `EX_TEMPFAIL`, chosen so schedulers treat "waiting on a person" as retryable
rather than broken; 76 sits beside it for the same reason. Neither means the run went
wrong — a scheduler should distinguish both from exit 1.

The run directory accumulates one file per payload edge plus `<node>.out` for every
node's output, successful or not. A failed run leaves its evidence behind; nothing is
held only in memory.

## Writing good prompts and steps

Prompts are where a well-structured workflow still produces bad output. The generated
templates give you the mechanics:

- **Payload placeholders.** `{{name}}` is replaced at run time with the contents of
  the payload file `name` — for every payload the node's `reads` list declares.
- **The feedback placeholder.** `{{feedback}}` is empty on a first attempt. When the
  node is re-entered through a loop edge, it carries the failing checker's output.
  Write the prompt so both cases read naturally — the generated template includes an
  "if the section above is empty, this is your first attempt" pattern for exactly
  this.
- **Authoring notes are free.** HTML comments (`<!-- ... -->`) are stripped before
  the prompt is sent, so you can annotate templates for future maintainers without
  spending tokens or distracting the model.

Steps are plain bash: exit 0 routes the `pass` edge, non-zero routes `fail`, and
everything printed to stdout/stderr becomes the payload the next node reads. Print
what the downstream node actually needs — a checker that fails silently gives the
retrying producer nothing to fix.

## Platform notes: Windows

Everything here is from observed behavior on a real Windows 11 machine; all of it is
pinned by tests that run in the Windows CI job.

- **Text encoding.** Windows' default text encoding is cp1252, not UTF-8. Every file
  read and write in this project passes `encoding="utf-8"` explicitly. If you extend
  the scripts, do the same — the failure mode is silent until a non-ASCII character
  (an em dash in generated prose, a minus sign in a vendored JS file) hits the
  codec.
- **Bash resolution.** `run_step` never invokes an unqualified `bash`. Windows'
  `CreateProcess` searches System32 *before* PATH, and System32's `bash.exe` is the
  WSL launcher — it re-tokenizes the command line POSIX-style (eating unquoted
  backslashes) and can't see Windows drive paths. The runner looks for Git's bash
  under `%ProgramFiles%`, then for a non-System32 `bash` on PATH, and otherwise
  stops with an error naming `WORKFLOW_BASH`. Step paths are passed with forward
  slashes because msys bash re-parses its command line when launched from a native
  process.
- **The `claude.CMD` shim.** npm installs `claude` on Windows as a `.CMD` batch
  shim. Anything routed through `cmd.exe` truncates a multi-line argument at the
  first newline — silently — and caps the whole command line at 8191 characters.
  This is why prompts travel on stdin (see [the traps](#the-traps)); it would bite
  any tool passing real prompts to the shim via argv.
- **`isatty` is not "a human is watching".** Windows console handles report
  `isatty() == true` even for `NUL`. The runner treats EOF on stdin as "nobody is
  there" and parks (exit 75) instead of crashing.

## Troubleshooting

**The diagram in the HTML artifact renders blank.**
The artifact was rendered without Playwright, so it falls back to loading Mermaid
from a CDN — and you're viewing it offline or in a sandboxed viewer that blocks
network. The renderer prints exactly why it fell back at render time. Fix:
`pip install playwright && playwright install chromium`, then re-render; the diagram
is then pre-rendered to inline SVG and the artifact works anywhere. (First
pre-render on a machine downloads `mermaid.min.js` once, to `~/.cache/workflowwright/`.)

**The generated `workflow.py` won't import.**
If the error is a `NameError` on `true`, `false`, or `null`, someone regenerated the
node tables with `json.dumps` — see [trap 1](#the-traps). If it's a codec or syntax
error mentioning an unexpected byte, the file was written without UTF-8 — see
[trap and platform notes above](#platform-notes-windows). Regenerate with the
current scaffolder.

**A retry loop never converges — the same failure keeps coming back.**
Check the loop edge carries `"loop": true` and names a payload: that is what routes
the checker's output back to the producer as `{{feedback}}`. A producer retried
without feedback doesn't know what failed and usually makes a different first
mistake instead of a fix. Also confirm the checker actually prints *why* it failed —
`exit 1` with no output gives the producer nothing.

**The workflow exits 76 every time and never gets further.**
That is delegate mode working: it parks at each agent node by design. Write the answer
to the `.result.md` path the message names, then rerun with the *same* `--run-dir` —
a different run directory has no `driver-state.json` and starts over. If you meant to
run unattended, drop `--delegate` and unset `WORKFLOW_DELEGATE`.

**The workflow exits 75 and I didn't expect it.**
A human node was reached with nobody at stdin — that's parking, not a crash (see
[exit codes](#running-a-generated-workflow)). Review the run directory it printed,
then continue with `--from <the-next-node>`. If you expected an interactive prompt,
you're running it from something that detaches stdin (CI, cron, a task runner).

**An agent's answer looks like it only saw part of the prompt.**
On current code, it can't be argv truncation — prompts travel on stdin. Check the
prompt template's `reads` list actually declares the payload you expected to be
substituted; an undeclared `{{name}}` placeholder is left as-is, not filled. If
you're on a fork that reverted to argv delivery, see [trap 4](#the-traps).

## The traps

Six things that look like bugs and are not. Each is pinned by a test; if you "fix"
one, the suite will tell you which conviction you've just violated.

1. **`pprint.pformat`, not `json.dumps`, emits the node and edge tables into
   generated Python.** It looks like a quirky serialization choice. But JSON's
   `true` / `false` / `null` are syntactically valid Python *names*, so
   `json.dumps` output passes `py_compile` and then raises `NameError` at import —
   the worst kind of failure, one compile step past where you looked.
   Pinned by `test_generated_module_imports`.

2. **`htmlLabels: false` in the Mermaid config, and node labels use `<br/>` but
   never `<small>`.** It looks like forgone formatting. But with HTML labels on,
   headless rendering mismeasures text and clips node labels; with them off,
   `<br/>` is the only markup that survives. Pinned by `test_no_small_tags_in_labels`.

3. **Retry attempts are counted against the node a failure edge *re-enters*, not
   the node that failed.** It looks backwards — surely the failing node should be
   charged? But the node that fails is usually the checker, and a checker failing
   is the checker doing its job. Counted that way, the first legitimate rejection
   exhausts the loop. Pinned by
   `test_checker_failing_repeatedly_does_not_consume_its_own_retries`.

4. **The agent prompt travels on stdin, never argv.** It looks like an odd
   asymmetry — the flags are argv. But prompts carry whole payload files: they
   exceed the 8191-character `cmd.exe` ceiling, and npm's `claude.CMD` shim
   truncates a multi-line argv prompt at the first newline. Both failures are
   silent — the agent answers a fragment and the run looks fine. Verified against a
   real CLI before landing. Pinned by `test_large_prompt_survives_the_process_boundary`.

5. **`run_step` resolves bash explicitly and hard-fails naming `WORKFLOW_BASH`,
   rather than falling back to `"bash"`.** The fallback looks harmless — surely
   some bash beats no bash? But an unqualified `"bash"` resolves through
   `CreateProcess`, which searches System32 before PATH and finds WSL's launcher,
   which mangles Windows paths. A silent fallback would reintroduce that bug
   invisibly — the same failure class as a swallowed exception. Pinned by
   `test_missing_bash_fails_loudly_naming_workflow_bash`.

6. **`ask_human` parks on `EOFError`, not only on `not isatty()`.** The TTY check
   looks sufficient. But a TTY check is a poor proxy for "a human is watching" —
   defeated by piped stdin, CI, cron, and Windows console handles, which report
   `isatty() == true` even for `NUL`. EOF on a claimed TTY means nobody is there;
   the run parks at 75 with the same explanation either way. Pinned by
   `test_human_node_parks_instead_of_self_approving`.

## Maintaining the landing page

`docs/index.html` is generated, not hand-edited. `docs/build_site.py` holds the markup
and styles and embeds the diagram by extracting the inline SVG from
`examples/ticket-to-pr.html` — so the picture on the site is the tool's real output for
the bundled example spec.

```sh
make site         # rebuild docs/index.html
make site-check   # fail if it is stale (CI runs this)
```

To change the diagram, edit `skill/assets/example-spec.json`, run `make example` on a
machine with Playwright installed, then `make site`. Re-rendering without Playwright
replaces the artifact's inline SVG with a CDN fallback, and `build_site.py` refuses to
build from that rather than shipping a page whose diagram needs the network.

The page is intentionally self-contained: no CDN, no web font, no analytics, no external
requests of any kind — the same constraint the artifacts hold themselves to.

## Extending it

`runner.py` is the only place a generated workflow leaves the Python process — three
functions: `run_agent`, `run_step`, `ask_human`. Swap the CLI for an SDK, add
tracing, enforce a token budget, or mock the whole outside world for tests, all in
that one file. `workflow.py` never needs to know. For quick substitutions that don't
merit an edit — pointing tests at a stub, trying a different CLI — `WORKFLOW_AGENT_CLI`
does it from the environment.
