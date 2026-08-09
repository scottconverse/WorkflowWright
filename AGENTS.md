# WorkflowWright, for agents that are not Claude Code

Claude Code discovers this repo as a plugin. Other agent hosts do not, so this file
is the entry point for them.

**The instructions live in [`skill/SKILL.md`](skill/SKILL.md).** Read it. It describes
three modes — design, critique, and scaffold — and the reference material it points to
in `skill/references/`. Nothing in it is Claude-specific.

## Installing

Codex and Antigravity both read skills as a directory containing `SKILL.md` with
`name` and `description` frontmatter — the same shape `skill/` already has. Installing
is a copy. There is no adapter and no conversion step:

```sh
git clone https://github.com/scottconverse/WorkflowWright.git

# Codex
cp -r WorkflowWright/skill ~/.codex/skills/workflowwright

# Antigravity (machine-wide; use .agents/skills/ in a project instead)
cp -r WorkflowWright/skill ~/.gemini/config/skills/workflowwright
```

On Windows those are `%USERPROFILE%\.codex\skills\workflowwright` and
`%USERPROFILE%\.gemini\config\skills\workflowwright`. Delete the directory to
uninstall.

Both were verified by installing to those paths and then asking each host, without
naming any file, to use the skill and run its renderer. Codex and Antigravity each
found it by description alone, read it, executed the script, and reported the
validator's exit code — so discovery, natural-phrasing triggering, and execution all
work in both.

One difference showed up in that test. Under Codex's sandbox the rendered artifact came
back with a CDN script tag instead of an inline SVG; Antigravity produced the inline
SVG. The renderer pre-draws the diagram with headless Chromium when it can, and a
sandbox that blocks launching a browser makes it fall back — correctly, and it prints
the reason. The artifact still renders in a normal browser; it just needs network. If
you want self-contained artifacts from a sandboxed host, render them outside the
sandbox.

Antigravity's own customization guide documents the layout as
`skills/<name>/SKILL.md` plus optional `scripts/`, `references/`, `examples/`, and
`resources/`; `skill/` satisfies it as-is, and carries an extra `assets/` directory
that the host simply ignores.

Antigravity also loads a project-local `.agents/skills/` ahead of the machine-wide
directory, so a team can check the skill into a repository instead.

## Installing anywhere else

If the host has a skills directory, the same copy works. If it does not, point the
agent at `skill/SKILL.md` directly — it is ordinary markdown with no host-specific
machinery in it.

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

**Nothing about triggering, if the host has a skills directory.** The frontmatter
`description` is written for skill-selection and Codex uses the same convention, so it
triggers on natural phrasing there too. Only a host with no skills mechanism at all
needs you to name the file.

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
