#!/usr/bin/env python3
"""Compile a workflow spec into a runnable orchestrator.

Usage:
    python3 scaffold_workflow.py spec.json --out ./my-workflow

Generates a package where the orchestration is deterministic Python and agents are
invoked as separate processes. That separation is the point: it is what makes attempts
countable, check output readable, failures routable, and single nodes testable.

Regenerating overwrites workflow.py and runner.py. It never overwrites anything in
prompts/ or steps/ — those are yours to fill in and keep.
"""

import argparse
import json
import pprint
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from render_workflow import load_spec, validate  # noqa: E402


# --------------------------------------------------------------------- runner.py

RUNNER = '''"""Process boundaries: how this workflow talks to agents, shells, and people.

Everything that leaves the Python process goes through here, so there is exactly one
place to change when you swap the agent CLI for an SDK, add tracing, or set a budget.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass


@dataclass
class Result:
    ok: bool
    output: str = ""
    session_id: str | None = None


AGENT_TIMEOUT = int(os.environ.get("WORKFLOW_AGENT_TIMEOUT", "1800"))
STEP_TIMEOUT = int(os.environ.get("WORKFLOW_STEP_TIMEOUT", "3600"))
PERMISSION_MODE = os.environ.get("WORKFLOW_PERMISSION_MODE", "acceptEdits")


def run_agent(prompt, *, session_id=None, model=None, tools=None, cwd=None):
    """Invoke an agent as a subprocess and return its result plus session id.

    Resuming matters on retries. A producer that just failed already holds the context
    of what it was attempting; what it lacks is the news that it failed and why.
    Starting a fresh session throws away the former to deliver the latter, and usually
    produces a different first mistake rather than a fix.
    """
    cmd = ["claude", "-p", "--output-format", "json", "--permission-mode", PERMISSION_MODE]
    if session_id:
        cmd += ["--resume", session_id]
    if model:
        cmd += ["--model", model]
    if tools:
        cmd += ["--allowed-tools", *tools]
    cmd.append(prompt)

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, cwd=cwd, timeout=AGENT_TIMEOUT
        )
    except subprocess.TimeoutExpired:
        return Result(False, f"agent exceeded {AGENT_TIMEOUT}s timeout", session_id)
    except FileNotFoundError:
        return Result(False, "the `claude` CLI is not on PATH", session_id)

    if not proc.stdout.strip():
        return Result(False, proc.stderr.strip() or "agent produced no output", session_id)

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return Result(False, f"unparseable agent output: {proc.stdout[:500]}", session_id)

    new_session = data.get("session_id") or session_id
    text = str(data.get("result", ""))
    if proc.returncode != 0 or data.get("is_error"):
        return Result(False, text or proc.stderr.strip(), new_session)
    return Result(True, text, new_session)


def run_step(script, *, cwd=None):
    """Run a deterministic step. Exit status is the verdict; output is the payload."""
    try:
        proc = subprocess.run(
            ["bash", str(script)], capture_output=True, text=True,
            cwd=cwd, timeout=STEP_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return Result(False, f"step exceeded {STEP_TIMEOUT}s timeout")
    return Result(proc.returncode == 0, (proc.stdout + proc.stderr).strip())


NEEDS_HUMAN = 75  # EX_TEMPFAIL: the run is not wrong, it is waiting on a person


def ask_human(label, detail, context_path):
    """Block for a decision when someone is watching; park the run when nobody is.

    Failing loudly beats guessing. An unattended run that silently approves its own
    work removes the only check that node existed to provide.
    """
    print(f"\\n=== {label} ===\\n{detail}\\nContext: {context_path}\\n")
    if not sys.stdin.isatty():
        print(
            "No interactive terminal, so this run stops here rather than deciding for "
            f"you. Review the context above and rerun with --from to continue.",
            file=sys.stderr,
        )
        raise SystemExit(NEEDS_HUMAN)
    answer = input("Approve? [y/N] ").strip().lower()
    return Result(answer in ("y", "yes"), f"human answered: {answer or 'no'}")
'''


# ------------------------------------------------------------------ workflow.py

WORKFLOW_HEADER = '''#!/usr/bin/env python3
"""{name} — {goal}

Trigger: {trigger}
Isolation: {isolation}

Generated from spec.json. Regenerating overwrites this file, so put durable edits in
prompts/ and steps/ (never overwritten) or stop regenerating once you take ownership.

Run:
    python3 workflow.py                 # full run
    python3 workflow.py --only build    # one node, against the last run's payloads
    python3 workflow.py --from verify   # resume partway
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from runner import Result, ask_human, run_agent, run_step

HERE = Path(__file__).parent
ENTRY = {entry!r}

# --- generated from spec.json ------------------------------------------------
NODES = {nodes}

EDGES = {edges}
# -----------------------------------------------------------------------------
'''

WORKFLOW_BODY = '''

class Context:
    """Payloads on disk, sessions in memory.

    Payloads are real files rather than variables so that a single node can be rerun
    against a fixed input, and so a failed run leaves behind something readable.
    """

    def __init__(self, run_dir: Path, workdir: Path):
        self.run_dir = run_dir
        self.workdir = workdir
        self.sessions: dict[str, str] = {}
        self.feedback: str | None = None
        run_dir.mkdir(parents=True, exist_ok=True)

    def read(self, name: str) -> str:
        path = self.run_dir / name
        return path.read_text() if path.exists() else ""

    def write(self, name: str, text: str) -> None:
        path = self.run_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def prompt_for(self, node_id: str) -> str:
        """Fill a prompt template with the payloads this node declares it reads."""
        template = (HERE / "prompts" / f"{node_id}.md").read_text()
        # Authoring notes are for whoever maintains the prompt, not for the model.
        template = re.sub(r"<!--.*?-->", "", template, flags=re.DOTALL)
        for name in NODES[node_id].get("reads", []):
            template = template.replace("{{" + name + "}}", self.read(name))
        template = template.replace("{{feedback}}", self.feedback or "")
        return template.strip()


def log(message: str) -> None:
    stamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{stamp}] {message}", flush=True)


def next_node(node_id: str, conditions: tuple[str, ...]):
    for edge in EDGES:
        if edge["from"] == node_id and edge.get("when") in conditions:
            return edge
    return None


def run_node(node_id: str, ctx: Context) -> Result:
    node = NODES[node_id]
    kind = node["kind"]

    if kind == "code":
        return run_step(HERE / "steps" / f"{node_id}.sh", cwd=ctx.workdir)

    if kind == "agent":
        result = run_agent(
            ctx.prompt_for(node_id),
            session_id=ctx.sessions.get(node_id),
            model=node.get("model"),
            tools=node.get("tools"),
            cwd=ctx.workdir,
        )
        if result.session_id:
            ctx.sessions[node_id] = result.session_id
        return result

    if kind == "human":
        return ask_human(node["label"], node.get("detail", ""), ctx.run_dir)

    return Result(False, f"unknown node kind: {kind}")


ESCALATION_MODEL = "opus"

# A bound only means something for nodes a failure edge loops back into — those are
# the ones that can be re-entered indefinitely. A checker that fails is doing its job,
# not consuming a retry of its own.
RETRY_TARGETS = {e["to"] for e in EDGES if e.get("when") == "fail"}


def give_up(node_id: str, ctx: Context, limit: int) -> int:
    node = NODES[node_id]
    action = node.get("on_exhausted", "fail")
    log(f"  {node_id}: giving up after {limit} attempt(s) -> {action}")
    if action == "human":
        outcome = ask_human(
            f"{node_id} could not be completed automatically",
            node.get("detail", ""),
            ctx.run_dir,
        )
        return 0 if outcome.ok else 1
    return 1


def drive(ctx: Context, start: str) -> int:
    attempts: dict[str, int] = defaultdict(int)
    current = start

    while current:
        node = NODES[current]
        attempts[current] += 1
        limit = node.get("max_attempts", 1)
        bounded = current in RETRY_TARGETS

        if bounded and attempts[current] > limit:
            # Escalation is a bet that the task was merely hard, not impossible. It
            # only pays off when a trustworthy check told us the cheap attempt failed.
            if node.get("on_exhausted") == "escalate-model" and not node.get("_escalated"):
                node["_escalated"] = True
                node["model"] = ESCALATION_MODEL
                node["max_attempts"] = limit + 1
                limit = node["max_attempts"]
                log(f"  {current}: escalating to {ESCALATION_MODEL} for a final attempt")
            else:
                return give_up(current, ctx, limit)

        suffix = f" (attempt {attempts[current]}/{limit})" if bounded else ""
        log(f"{current} [{node['kind']}] {node['label']}{suffix}")

        result = run_node(current, ctx)
        ctx.write(f"{current}.out", result.output)
        ctx.feedback = None

        if result.ok:
            edge = next_node(current, ("always", "pass"))
            if edge is None:
                log(f"done — {current} was terminal")
                return 0
            if edge.get("payload") and result.output:
                ctx.write(edge["payload"], result.output)
            current = edge["to"]
            continue

        log(f"  failed: {result.output[:300]}")

        edge = next_node(current, ("fail",))
        if edge is None:
            # Nothing to route to, so this failure ends the run.
            return give_up(current, ctx, limit)

        if edge.get("payload"):
            ctx.write(edge["payload"], result.output)
        # A loop edge carries the failure back as feedback rather than as a fresh task.
        ctx.feedback = result.output if edge.get("loop") else None
        current = edge["to"]

    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", default=str(HERE / "runs" / "latest"),
                    help="where payloads live")
    ap.add_argument("--workdir", default=".", help="where code and agents execute")
    ap.add_argument("--only", help="run a single node against existing payloads")
    ap.add_argument("--from", dest="start", help="start partway through")
    args = ap.parse_args()

    ctx = Context(Path(args.run_dir), Path(args.workdir).resolve())

    if args.only:
        if args.only not in NODES:
            print(f"unknown node: {args.only}", file=sys.stderr)
            return 2
        result = run_node(args.only, ctx)
        ctx.write(f"{args.only}.out", result.output)
        print(result.output)
        return 0 if result.ok else 1

    return drive(ctx, args.start or ENTRY)


if __name__ == "__main__":
    raise SystemExit(main())
'''


# ------------------------------------------------------------------- templates

PROMPT_TEMPLATE = """<!-- Prompt for node `{node_id}` ({model}).

{detail}

Placeholders below are substituted at run time with the payloads this node reads.
The feedback placeholder is empty on the first attempt and carries the failure output
when this node is reached by a retry edge — write the prompt so both cases read
naturally.

This comment is stripped before the prompt is sent, so notes to yourself are free.

Keep this specific. A vague prompt here is the most common reason a well-structured
workflow still produces bad output. -->

{reads_block}
## Your task

{detail}

{feedback_block}
## What to produce

TODO: state exactly what this node must output, and where it should be written.
The next node expects: {writes}
"""

STEP_TEMPLATE = """#!/usr/bin/env bash
# Step `{node_id}` — {label}
#
# {detail}
#
# Exit status is the verdict: zero means pass, non-zero routes down this node's
# fail edge. Everything on stdout and stderr becomes the payload the next node
# reads, so print what the downstream node actually needs.
set -euo pipefail

echo "TODO: implement {node_id}" >&2
exit 1
"""

README_TEMPLATE = """# {name}

{goal}

- **Trigger:** {trigger}
- **Isolation:** `{isolation}`

Generated from `spec.json`. The diagram and design doc come from the same file, so
edit the spec and regenerate rather than editing outputs by hand.

## Layout

| Path | Regenerated? | What it is |
|---|---|---|
| `workflow.py` | yes, overwritten | Orchestration: the node table, the driver, retry bounds |
| `runner.py` | yes, overwritten | The only place the workflow leaves the Python process |
| `prompts/*.md` | no, yours | One prompt per agent node |
| `steps/*.sh` | no, yours | One script per code node |
| `spec.json` | source | Edit this, then regenerate |
| `runs/` | — | Payloads from each run |

## Before it will run

{todo_list}

## Running it

```bash
python3 workflow.py                  # full run
python3 workflow.py --only {sample}   # one node against the last run's payloads
python3 workflow.py --from {sample}   # resume partway through
```

`--only` is the reason payloads are files rather than variables: you can rerun one
node against a fixed input instead of replaying the whole workflow to reach it.

## Knobs

Environment variables, all optional:

- `WORKFLOW_AGENT_TIMEOUT` (default 1800s)
- `WORKFLOW_STEP_TIMEOUT` (default 3600s)
- `WORKFLOW_PERMISSION_MODE` (default `acceptEdits`)

## A note on the shape

Checks are separate nodes from the things they check. That costs a little plumbing
and buys four things: attempts you can count and cap, check output you can read and
diff, failures you can route somewhere other than back to the same agent, and halves
you can swap independently. Folding a check into its producer's prompt gives all four
back.
"""


def generate(spec, out: Path, force: bool):
    out.mkdir(parents=True, exist_ok=True)
    (out / "prompts").mkdir(exist_ok=True)
    (out / "steps").mkdir(exist_ok=True)

    nodes = {n["id"]: n for n in spec["nodes"]}

    # Always regenerated — these are compiled artifacts.
    (out / "runner.py").write_text(RUNNER)
    (out / "workflow.py").write_text(
        WORKFLOW_HEADER.format(
            name=spec["name"],
            goal=spec["goal"],
            trigger=spec["trigger"],
            isolation=spec.get("isolation", "none"),
            entry=spec["entry"],
            # pprint, not json.dumps: JSON's true/false/null are bare names in
            # Python and would blow up at import rather than at compile time.
            nodes=pprint.pformat(nodes, indent=4, sort_dicts=False, width=88),
            edges=pprint.pformat(spec["edges"], indent=4, sort_dicts=False, width=88),
        )
        + WORKFLOW_BODY
    )
    (out / "workflow.py").chmod(0o755)
    (out / "spec.json").write_text(json.dumps(spec, indent=2) + "\n")

    # Never overwritten — these hold the actual work.
    created, skipped = [], []
    for node in spec["nodes"]:
        nid, kind = node["id"], node.get("kind")
        if kind == "agent":
            path = out / "prompts" / f"{nid}.md"
            reads = node.get("reads", [])
            reads_block = (
                "\n".join(
                    f"## {name}\n\n{{{{{name}}}}}\n" for name in reads
                )
                if reads
                else ""
            )
            feedback_block = (
                "## Previous attempt failed\n\n{{feedback}}\n\n"
                "If the section above is empty this is your first attempt. If it has "
                "content, fix what it describes rather than reworking the approach.\n"
                if any(
                    e.get("to") == nid and e.get("loop") for e in spec["edges"]
                )
                else ""
            )
            body = PROMPT_TEMPLATE.format(
                node_id=nid,
                model=node.get("model", "default model"),
                detail=node.get("detail", ""),
                reads_block=reads_block,
                feedback_block=feedback_block,
                writes=", ".join(node.get("writes", [])) or "(nothing declared)",
            )
        elif kind == "code":
            path = out / "steps" / f"{nid}.sh"
            body = STEP_TEMPLATE.format(
                node_id=nid, label=node["label"], detail=node.get("detail", "")
            )
        else:
            continue

        if path.exists() and not force:
            skipped.append(path)
            continue
        path.write_text(body)
        if kind == "code":
            path.chmod(0o755)
        created.append(path)

    todo = []
    for node in spec["nodes"]:
        if node.get("kind") == "code":
            todo.append(f"- [ ] `steps/{node['id']}.sh` — {node.get('detail', '')}")
        elif node.get("kind") == "agent":
            todo.append(f"- [ ] `prompts/{node['id']}.md` — {node.get('detail', '')}")
    for question in spec.get("open_questions", []):
        todo.append(f"- [ ] Open question: {question}")

    sample = next(
        (n["id"] for n in spec["nodes"] if n.get("kind") == "agent"), spec["entry"]
    )
    (out / "README.md").write_text(
        README_TEMPLATE.format(
            name=spec["name"],
            goal=spec["goal"],
            trigger=spec["trigger"],
            isolation=spec.get("isolation", "none"),
            todo_list="\n".join(todo),
            sample=sample,
        )
    )
    return created, skipped


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("spec")
    ap.add_argument("--out", required=True, help="output package directory")
    ap.add_argument(
        "--force",
        action="store_true",
        help="also overwrite existing prompts and steps (destructive)",
    )
    args = ap.parse_args()

    spec = load_spec(args.spec)
    problems = validate(spec)
    if problems:
        print("refusing to scaffold a spec with structural problems:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print(
            "\nFix these in the spec first — they become real defects in generated "
            "code, and an unbounded retry loop is much cheaper to fix here.",
            file=sys.stderr,
        )
        return 2

    out = Path(args.out)
    created, skipped = generate(spec, out, args.force)

    print(f"scaffolded {spec['name']} into {out}/")
    for path in created:
        print(f"  created  {path.relative_to(out)}")
    for path in skipped:
        print(f"  kept     {path.relative_to(out)} (already exists)")
    print(f"\nNext: fill in the TODOs listed in {out / 'README.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
