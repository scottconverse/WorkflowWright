# Changelog

## v0.2.0

**Anyone who installed v0.1.0 through the desktop or web client should update.**
That path downloads the release archive, so it served the code below until this
release; the Claude Code plugin and the `git clone` installs track the branch and
already had the fixes.

### Security

Five defects, each reproduced before being fixed and pinned by a test that fails
against the original code. All five let content from a `spec.json` — a file this
tool tells you to keep, share and regenerate from, and which critique mode
reconstructs from scripts and CI configs somebody else wrote — escape the
container it was written into.

- **The shared HTML artifact executed script from a node label.** The Mermaid
  block was the one value on the page not passed through `esc()`, and a browser
  parses that block long before Mermaid runs, so a `<script>` tag in a label
  became a live script element on open. Confirmed executing in headless Chromium.
- **A newline in a label or detail became a shell command.** Generated step
  scripts carry both as `#` comments; a newline ended the comment and put what
  followed at the start of a command line, above the stub's own `exit 1`. It ran
  the first time the workflow reached that step.
- **`spec.name` wrote outside `--out`.** A name of `../../docs/index` placed the
  three rendered files wherever it pointed, over whatever was already there.
- **An edge `payload` wrote outside the run directory at run time**, with the
  node's output as content and the spec choosing the path.
- **A mistyped `WORKFLOW_*_CLI` killed the whole run** instead of failing the
  node. Only `FileNotFoundError` was caught, so pointing at a directory or a
  non-executable — the ordinary near-miss when typing a path by hand — escaped as
  a traceback, taking the event log, the fail edge and the state file with it.

Four spec fields become filesystem paths — `name`, node `id`, edge `payload`,
node `evidence` — and all four are now validated together. The generated runner
re-checks at write time, because the validator runs when a package is generated
and a package can be copied or hand-edited before it is run.

### Fixed

- A successful run died on its last line on a cp437 console. An em dash reached
  stdout through the driver's `print` wrapper, so the run exited non-zero after
  doing all its work, never recorded `run_end`, and left `driver-state.json`
  live — leaving a finished run resumable.
- Delegate mode logged agent parks and not human parks, so in the mode with a
  person reading the log, a decision appeared in answer to a question the log
  never recorded being asked.
- `--report` crashed on a log line that was valid JSON but not a record. One bad
  line in one stale run directory cost the aggregate for every healthy run.
- `max_attempts` given as a quoted number — a one-character JSON mistake — raised
  a `TypeError` inside the validator instead of being reported as a spec problem.
- `make uninstall` was an `rm -rf` on a variable. It now refuses a directory with
  no `SKILL.md` and refuses a version-controlled working copy.
- Markdown tables broke on ordinary content: a `|` in a `detail` split the row and
  a newline ended it.

### Added

- **Per-node backends.** An agent node names which system runs it — `claude`,
  `codex`, `agy`, or `openai-compat` with an `endpoint` — and the design doc
  gained a **Payload goes to** column that names the destination and flags
  anything leaving the machine. The field is spelled for the protocol rather than
  "local" because privacy comes from the address being loopback, not from the
  model being self-hosted.
- **`workflow.py --report`** reads every `run.jsonl` under `runs/` and counts
  runs, attempts, successes, failures and missing evidence per node, grouped by
  backend. It reports and deliberately does not route.
- An append-only `run.jsonl` event log, and a `driver-state.final.json` receipt
  kept when a run finishes.
- CI on Python 3.14.
- Design guidance against splitting one stage across parallel agents that cannot
  talk to each other, which measures worse than not splitting at all.

### Tests

133 → 159, green on Linux 3.10–3.14 and on Windows.

## v0.1.0

First public release.
