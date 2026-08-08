# WorkflowWright, for agents that are not Claude Code

Claude Code discovers this repo as a plugin. Other agent hosts do not, so this file
is the entry point for them.

**The instructions live in [`skill/SKILL.md`](skill/SKILL.md).** Read it. It describes
three modes — design, critique, and scaffold — and the reference material it points to
in `skill/references/`. Nothing in it is Claude-specific.

## What works anywhere

The two scripts are Python 3.10+ using only the standard library. No install, no
dependency, no API key, and they never call a model:

```sh
python3 skill/scripts/render_workflow.py   spec.json --out ./out
python3 skill/scripts/scaffold_workflow.py spec.json --out ./my-workflow
```

**Running a generated workflow works anywhere too, in delegate mode:**

```sh
python3 workflow.py --delegate
```

The run parks at each agent node, writes the composed prompt to
`<run-dir>/<node>.prompt.md`, and exits 76. You do that work, write the answer to
`<node>.result.md`, and run the same command again. Human gates behave the same way,
via `<node>.decision.md` and `<node>.answer.md`.

That contract is deliberately dumb — read a file, write a file, rerun a command, check
an exit code — so any agent in any host can drive a workflow without the host knowing
anything about WorkflowWright. Routing, retry ceilings, evidence gates, and the run
budget are enforced by the driver either way; only the model call moves.

## What does not work outside Claude Code

**Automatic triggering.** The `description` in `SKILL.md`'s frontmatter is written for
Claude's skill-selection. Elsewhere, point your agent at `SKILL.md` explicitly.

**Unattended subprocess mode.** Without `--delegate`, the runner shells out to an agent
CLI using Claude's flag vocabulary (`-p`, `--output-format json`, `--permission-mode`,
`--resume`) and parses Claude's JSON response envelope. `WORKFLOW_AGENT_CLI` swaps the
command but not the protocol, so pointing it at a different CLI fails on the response
shape rather than the command. Adapting it means editing `run_agent` in the generated
`runner.py`, which is the single place the workflow leaves the Python process.

That adapter is not built. It would be untested speculation until someone actually
runs this against another CLI — the same reasoning as
[ADR 0001](docs/adr/0001-loopx-compile-target-deferred.md). If you are that someone,
open an issue and say which CLI; that is the trigger to build it properly.
