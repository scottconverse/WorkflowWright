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
cd WorkflowWright

# Codex
python3 scripts/install.py ~/.codex/skills/workflowwright

# Antigravity (machine-wide; use .agents/skills/ in a project instead)
python3 scripts/install.py ~/.gemini/config/skills/workflowwright
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

## What used to not work outside Claude Code

Both entries on this list have been retired, so it is kept as a record of what was
checked rather than as a list of limitations.

**Nothing about triggering, if the host has a skills directory.** The frontmatter
`description` is written for skill-selection and Codex uses the same convention, so it
triggers on natural phrasing there too. Only a host with no skills mechanism at all
needs you to name the file.

**Nothing about unattended runs, either, once the node says which system runs it.**
This used to be the limitation on this list, and it is not one any more. An agent node
carries a `backend` — `claude` (the default), `codex`, `agy`, or `openai-compat` with an
`endpoint` — and the runner speaks each one's own vocabulary and parses its own reply
shape. `WORKFLOW_CODEX_CLI` and `WORKFLOW_AGY_CLI` point at the binaries, which matters
because Antigravity is usually not on PATH.

Two facts about those CLIs were established by running them rather than by reading
about them, and both are load-bearing: Codex takes its prompt on stdin via `-` and
resumes by session id, while **Antigravity ignores stdin entirely** — its prompt goes on
the command line, so it alone keeps an argv ceiling and refuses an oversized prompt
rather than letting the OS truncate one into a confident answer to half a question.

So a workflow runs unattended under Codex or Antigravity by naming that backend in the
spec, with no edit to any generated file. `skill/references/spec-schema.md` has the
field reference and the reasoning about where each payload ends up.
