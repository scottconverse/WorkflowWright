# Changelog

## v0.2.2

- **The design doc and the generated package's own header promised isolation
  they do not create.** `isolation: worktree` printed as a bare fact; nothing in
  the generated code makes a worktree. Both now say so plainly next to the
  value, where someone deciding whether a run is safe will read it, not only in
  the project's separate documentation.
- **Critique mode's rubric never mentioned `backend`.** `design-method.md` has a
  full section on choosing which system runs a node, including that a
  self-hosted node needs something checking its output — a rule the validator
  enforces. The critique rubric's "uniform model selection" pattern covered
  tier only, so reviewing an existing workflow would never surface either the
  free-backend opportunity or the missing check. Extended to match.

## v0.2.1

**v0.2.0's archive could not be installed.** Its `SKILL.md` description was
1252 characters and the claude.ai uploader rejects anything over 1024, so the
desktop and web route — the one v0.2.0 existed to fix — refused the file. The
description is now 1019, and a test enforces the limit, because nothing else in
the repo fails when it grows: it stays invisible until an upload is rejected by
hand.

Also: `make install` merged rather than replaced. `cp -r skill/. DIR/`
overwrites the files it has and leaves behind any a newer version dropped, so an
upgrade produced a mixture of two releases. No file had ever been deleted
between releases, so nothing had gone wrong yet. `scripts/install.py` now
mirrors, reports what it added, updated and removed, and refuses the same two
cases the uninstaller does. The Codex and Antigravity instructions had the same
bug and now call it too.

## v0.2.0

**If you installed v0.1.0 by downloading the release archive — the desktop and
web client route — update.** The Claude Code plugin and the `git clone` installs
track the branch and already have these fixes.

### Security

Five defects, all in the same class: content taken from a `spec.json` was not
sufficiently constrained when it was written into a generated artifact, a
generated script, or an output path. A spec is a file this project tells you to
keep, share and regenerate from, and critique mode reconstructs one from material
somebody else wrote, so a spec is not automatically trusted input.

Affected surfaces, all fixed:

- The rendered HTML artifact.
- Generated step scripts and prompt files.
- Output paths for the renderer and the scaffolder.
- The generated runner's payload and evidence file handling.

Four spec fields are used to build filesystem paths — `name`, node `id`, edge
`payload`, node `evidence` — and all four are now validated as filenames rather
than paths. The generated runner re-checks at write time, because the validator
runs when a package is generated and a package can be copied or edited before it
is run.

A sixth fix in the same area: a mistyped `WORKFLOW_*_CLI` ended the whole run
instead of failing the node, taking the event log and the state file with it.

Each fix is covered by a test that fails against the previous code.

### Fixed

- A successful run could exit non-zero on a non-UTF-8 console after completing
  its work, without recording that it finished — which left a completed run
  looking resumable.
- Delegate mode recorded agent pauses but not human ones, so the log showed a
  decision with no record of the question.
- `--report` stopped on a malformed line in any run log, losing the summary for
  every healthy run alongside it.
- `max_attempts` given as a quoted number raised an error inside the validator
  instead of being reported as a spec problem.
- `make uninstall` was an `rm -rf` on a variable. It now refuses a directory with
  no `SKILL.md`, and refuses a version-controlled working copy.
- Markdown tables in the design doc broke on ordinary content in a `detail`.

### Added

- **Per-node backends.** An agent node names which system runs it — `claude`,
  `codex`, `agy`, or `openai-compat` with an `endpoint` — and the design doc
  gained a **Payload goes to** column naming the destination for every agent
  node, in bold when it leaves the machine. The field is spelled for the protocol
  rather than "local" because privacy comes from the address being loopback, not
  from the model being self-hosted.
- **`workflow.py --report`** reads every `run.jsonl` under `runs/` and counts
  runs, attempts, successes, failures and missing evidence per node, grouped by
  backend. It reports and deliberately does not route.
- An append-only `run.jsonl` event log, and a `driver-state.final.json` receipt
  kept when a run finishes.
- CI on Python 3.14.
- Design guidance against splitting one stage across parallel agents that cannot
  share what they find, which measures worse than not splitting at all.

### Tests

133 → 159, green on Linux 3.10–3.14 and on Windows.

## v0.1.0

First public release.
