# WorkflowWright

**[Website](https://scottconverse.github.io/WorkflowWright/)** ·
[Manual](docs/manual.md) ·
[Spec schema](skill/references/spec-schema.md) ·
[Example spec](skill/assets/example-spec.json)

**Agent automation fails for structural reasons, not prompting reasons.**

The model call that should have been a function. The retry loop with no ceiling. The
check folded into the producer's own turn, where nobody can see it or count it. The
approval gate in the middle of the pipeline that caps throughput at one person's
attention. None of these are fixed by a better prompt, because none of them are
prompting problems — they are assignment problems.

Three resources can do work, and they differ enormously:

| | Reliability | Marginal cost | Best at |
|---|---|---|---|
| **Code** | Deterministic | ~Zero | Anything whose output is fixed by its input |
| **Agents** | Variable | Tokens | Ambiguous input, novel output, judgment at scale |
| **Humans** | High judgment | Highest, and scarce | Taste, accountability, irreversible calls |

Designing an agent workflow is mostly the act of assigning each step to the cheapest
resource that can actually do it, and then defining what happens when that step fails.
Two errors account for most broken pipelines. The first is over-assigning to agents:
when you have an agent available, every step looks like an agent step, including the
ones a five-line script does deterministically for free. The second is interior
approval gates: each one serializes the entire workflow at one person's availability,
which is why "I want to review the plan" is usually better served by a written payload
you review after the fact than by a synchronous yes/no in the middle.

WorkflowWright is a Claude skill plus two standalone Python scripts that make those
decisions explicit — and then compile them into artifacts that cannot drift apart,
because all of them are generated from one file:

```
                 ┌─> design doc          (markdown)
   spec.json ────┼─> diagram             (Mermaid)
                 ├─> shareable artifact  (self-contained HTML, diagram pre-rendered)
                 └─> orchestrator        (runnable Python package)
```

Three modes, depending on what exists already:

- **Design** writes the spec by interviewing you — about one specific recent run of
  the process, ideally one that went wrong.
- **Critique** reconstructs a spec from whatever you have — a script, prompts, a CI
  config — and reviews the architecture against twelve failure patterns.
- **Scaffold** compiles an agreed spec into the orchestrator package.

## Install

This repo is a Claude Code plugin marketplace. Nothing to clone, no `make`, no Python:

```
/plugin marketplace add scottconverse/WorkflowWright
/plugin install workflowwright@workflowwright
```

And to remove it:

```
/plugin uninstall workflowwright
```

Not using Claude Code? The scripts are stdlib Python and run anywhere, and
`workflow.py --delegate` drives a workflow from any agent host — see
[AGENTS.md](AGENTS.md), which is honest about what does and does not carry over.

Working on the skill itself, or using the desktop or web client instead? Those read a
different copy — see
[installing and updating](docs/manual.md#installing-and-updating), which covers all
three places a skill can live, how to tell which one is actually running, and how to
remove each.

## Working on it

```sh
make test        # run the suite — no network, credentials, or token spend
make validate    # check the plugin and marketplace manifests
make example     # render the bundled example spec into examples/
make site        # rebuild the landing page in docs/ from that example
make install     # copy skill/ into ~/.claude/skills/   (make uninstall removes it)
make package     # build the archive for a claude.ai account upload
```

Then just describe the problem to Claude — the skill triggers on natural phrasing:

> "Every time a bug comes in I read the ticket, dig through the code, write a fix,
> run the tests, and open a PR. Can we automate that?"

> "My agent keeps looping on test failures and burning tokens without converging."

> "Should the step that moves the ticket be an agent or just an API call?"

Or drive the scripts directly, no Claude in the loop:

```sh
python3 skill/scripts/render_workflow.py   spec.json --out ./out
python3 skill/scripts/scaffold_workflow.py spec.json --out ./my-workflow
```

## What the scaffold produces

A package where orchestration is deterministic Python and agents are separate
processes:

| Path | Regenerated? | What it is |
|---|---|---|
| `workflow.py` | overwritten | Node table, driver, retry bounds, routing |
| `runner.py` | overwritten | The only place the workflow leaves the Python process |
| `prompts/*.md` | **never** | One prompt per agent node, with payload placeholders |
| `steps/*.sh` | **never** | One script per code node; exit status is the verdict |

It is a skeleton with honest TODOs — every generated step exits 1 until you fill it
in, on the principle that a stub returning success is worse than no stub at all.

Four things the generated driver gets right that are easy to get wrong by hand:

- **Retry accounting.** Attempts are counted against the node a failure edge
  *re-enters*, not the checker that failed — a checker that fails is doing its job,
  and counting attempts there exhausts the loop on the first legitimate rejection.
- **Session resume.** A producer that just failed already holds the context of what
  it was attempting; what it lacks is the news that it failed and why. Retries resume
  its session rather than starting cold, which usually produces a fix instead of a
  different first mistake.
- **Payloads as files.** Every edge's payload lands in a run directory, so
  `--only <node>` can rerun one node against a fixed input instead of replaying the
  whole workflow to reach it — and a failed run leaves something readable behind.
- **Prompts on stdin.** Prompts carry whole payload files and routinely exceed the
  8191-character ceiling of `cmd.exe` shims, which also truncate at the first
  newline — silently, so the agent answers a fragment and the run looks fine. stdin
  has no ceiling and no quoting hazards on any platform.

Agent nodes run one of two ways. By default each spawns an agent CLI, which is what
you want from a terminal, CI, or cron. With `--delegate` the run instead parks at
each agent node, writes the composed prompt to the run directory, and continues when
you leave the answer beside it — no CLI on PATH, and no nested session spending
tokens out of sight. That is the mode to use from inside an assistant such as Claude
Code or Cowork. Routing, retry ceilings, and payloads are identical either way; only
the model call moves.

## Three ways a run refuses to lie to you

- **[Evidence](docs/manual.md#proving-a-node-worked).** A node can name the artifact
  that proves it did its job. Report success without producing it and the node has
  failed — routed down its fail edge, counted against its retries, like any other
  failure. An exit code is a claim; the artifact is the proof. The bar is existence and
  non-emptiness, which catches the silent no-op and not much more, and the docs say so
  rather than letting the word "evidence" imply a guarantee.
- **[A run budget](docs/manual.md#the-run-budget).** `max_attempts` bounds each node
  alone and cannot see across nodes, so a producer and a checker on a loop edge can
  both honour their ceilings and still ping-pong forever. `budget.agent_calls` counts
  the whole run. Retries count, failed calls count, and the tally survives the pauses
  of delegate mode.
- **[Decision records](docs/manual.md#human-gates-and-decision-records).** Every human
  gate writes what was asked, what was decided, why, and when. In delegate mode a gate
  is answerable by writing a file, which is what makes an approval reachable at all
  without a terminal — and an answer that parses as neither yes nor no is recorded as
  not approved.

The [manual](docs/manual.md) covers all of this in depth, including
[six things that look like bugs and are not](docs/manual.md#the-traps).
Design decisions with lasting consequences are recorded in
[docs/adr/](docs/adr/).

## When not to use it

A task run twice a month by one person who enjoys doing it does not need a spec, a
diagram, and a retry ladder. The machinery pays off with repetition, with concurrency,
or when unattended reliability matters — and it costs real effort to build and
maintain. If that bar isn't met, the right tool is a single well-aimed check, one
script, or a better prompt, and the skill will tell you so.

## Requirements

- **Python 3.10+**, standard library only — no third-party packages. CI runs the
  suite on 3.10–3.13 on Linux and 3.13 on Windows.
- **Playwright** (optional) — with it, rendered HTML artifacts embed the diagram as
  inline SVG and work offline, in sandboxed viewers, and forever; without it, the
  HTML falls back to loading Mermaid from a CDN and needs network access to draw.
- **`claude` CLI** — needed only to run a generated workflow *unattended*. Designing,
  rendering, critiquing, and scaffolding never call a model at all, and
  `workflow.py --delegate` runs a workflow without any CLI by handing each agent node
  to whatever assistant session you are working in.

## Tests

88 tests, stdlib `unittest`, no dependencies: `make test`, or without make:

```sh
python -m unittest discover -s tests
```

No network access, no API credentials, no token spend — agent invocation is exercised
against a stub CLI that records its argv and reads its prompt from stdin. Several
tests pin regressions found while building rather than hypothetical failures; the six
worth knowing about are documented in [the traps](docs/manual.md#the-traps).

## License

[MIT](LICENSE)
