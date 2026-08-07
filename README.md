# agent-workflow-architect

A Claude skill for designing, critiquing, and scaffolding workflows in which
deterministic code, AI agents, and human judgment each handle the part they are actually
best at.

Most agent automation fails for structural reasons rather than prompting reasons: the
model call that should have been a function, the retry loop with no ceiling, the check
folded into the producer's own turn so nobody can see it or count it, the approval gate in
the middle that caps throughput at one person's attention. This skill makes those
decisions explicit, then compiles them into artifacts that cannot drift apart.

## The idea

Three resources can do work, and they differ enormously in cost and guarantees:

| | Reliability | Marginal cost | Best at |
|---|---|---|---|
| **Code** | Deterministic | ~Zero | Anything whose output is fixed by its input |
| **Agents** | Variable | Tokens | Ambiguous input, novel output, judgment at scale |
| **Humans** | High judgment | Highest, and scarce | Taste, accountability, irreversible calls |

Designing a workflow is mostly assigning each step to the cheapest resource that can
actually do it, then defining what happens when that step fails.

## One spec, four outputs

Everything revolves around a single `spec.json` describing nodes, edges, and who does
what. Design mode writes it, critique mode reconstructs it from an existing setup,
scaffold mode compiles it. Because all outputs derive from one file, the diagram, the
document, and the code can never disagree.

```
                      ┌─ design doc (.md)
                      ├─ diagram (.mermaid)
   spec.json  ────────┼─ artifact (.html, self-contained)
                      └─ runnable orchestrator (Python)
```

## Quick start

```bash
make install          # copy the skill into ~/.claude/skills/
make example          # render the bundled example into examples/
make test             # run the suite (no network, no credentials, no token spend)
```

Then, in Claude, just describe the problem — the skill triggers on natural phrasing:

> "Every time a bug comes in I read the ticket, dig through the code, write a fix, run the
> tests, and open a PR. Can we automate that?"

Or drive the scripts directly:

```bash
python3 skill/scripts/render_workflow.py   spec.json --out ./out
python3 skill/scripts/scaffold_workflow.py spec.json --out ./my-workflow
```

## What the scaffold generates

A package where orchestration is deterministic Python and agents are separate processes:

| Path | Regenerated | What it is |
|---|---|---|
| `workflow.py` | overwritten | Node table, driver, retry bounds, routing |
| `runner.py` | overwritten | The only place the workflow leaves the Python process |
| `prompts/*.md` | **never** | One prompt per agent node, with payload placeholders |
| `steps/*.sh` | **never** | One script per code node; exit status is the verdict |

It is a skeleton with honest TODOs — every generated step exits 1 until you fill it in, on
the principle that a stub returning success is worse than no stub at all.

Three things the generated driver gets right that are easy to get wrong by hand:

- **Retry accounting.** Attempts are counted against the node a failure edge *re-enters*,
  not the checker that failed. Counted the other way, the first check failure exhausts the
  loop immediately.
- **Session resume.** A producer that just failed already holds the context of what it was
  attempting; it only lacks the news that it failed and why. Retries resume its session
  rather than starting cold.
- **Payloads as files.** Every edge's payload lands in a run directory, so `--only <node>`
  can rerun one node against a fixed input instead of replaying the workflow to reach it.

## Layout

```
skill/           the skill itself — this is what gets installed
  SKILL.md       triggering description and mode routing
  references/    design method, critique rubric, patterns, spec schema
  scripts/       render_workflow.py, scaffold_workflow.py
  assets/        a complete worked example spec
tests/           48 tests, stdlib unittest, no dependencies
examples/        rendered output of the bundled example spec
```

## Tests

`make test` runs everything with no network access, no API credentials, and no token
spend — agent invocation is exercised against a stub CLI that records its argv.

Several tests lock in regressions found while building rather than hypothetical failures,
and are commented as such. The three worth knowing about:

- `json.dumps` emits `true`/`null`, which are syntactically valid Python *names*, so
  `py_compile` passes and the generated module explodes at import instead.
- Mermaid's `htmlLabels` mode mismeasures text under headless rendering, clipping node
  labels; turning it off fixes the clipping but means only `<br/>` survives in labels.
- A CDN-loaded diagram renders an empty box in a sandboxed viewer — which is exactly where
  a persisted artifact lives. The renderer pre-renders to inline SVG when Playwright is
  available and falls back to the CDN otherwise.

## Requirements

- Python 3.10+ for both scripts (CI covers 3.10-3.13). No third-party packages required.
- **Optional:** Playwright + Chromium, for pre-rendering the diagram to inline SVG. Without
  it the HTML loads Mermaid from a CDN — still fine in a normal browser, but not offline
  or in a sandboxed viewer. `pip install playwright && playwright install chromium`.
- The `claude` CLI on `PATH`, only to *run* a generated workflow.

## License

MIT. See [LICENSE](LICENSE).

## Credit

The framing that prompted this — assigning each step of a development process to code,
agents, or people rather than treating agent loops as the unit of design — came from
IndyDevDan's video on AI developer workflows. The vocabulary, method, rubric, and all code
here are original.
