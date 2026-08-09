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

Agent nodes run one of two ways, and the choice is about where you work rather than
what the workflow does:

    subprocess (default)  spawn an agent CLI. Right for a terminal, CI, or cron,
                          where an unattended run should go start to finish alone.
    delegate              park and let the assistant you are already talking to do
                          the node, then resume. Right when you work inside an
                          assistant and have no terminal to run this from.

Delegate mode is not a lesser path. The deterministic half — routing, retry
ceilings, payloads, isolation of one node from the next — is identical, because it
lives in the driver rather than here. Only the model call moves, and moving it means
no CLI on PATH, no nested session spending tokens out of sight, and every agent step
visible where you are working.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class Result:
    ok: bool
    output: str = ""
    session_id: str | None = None
    # False only when no model call actually happened, which is what separates
    # "the CLI is missing" from "the call ran and failed". The budget charges
    # for the second and not the first.
    launched: bool = True


AGENT_TIMEOUT = int(os.environ.get("WORKFLOW_AGENT_TIMEOUT", "1800"))
STEP_TIMEOUT = int(os.environ.get("WORKFLOW_STEP_TIMEOUT", "3600"))
PERMISSION_MODE = os.environ.get("WORKFLOW_PERMISSION_MODE", "acceptEdits")

# The agent CLI, overridable so tests can substitute a stub and so a different
# CLI can be swapped in without editing this file. Split with shlex so the
# override may carry its own arguments, e.g. "python /path/to/stub.py".
AGENT_CLI = shlex.split(os.environ.get("WORKFLOW_AGENT_CLI", "claude")) or ["claude"]

NEEDS_HUMAN = 75  # EX_TEMPFAIL: the run is not wrong, it is waiting on a person
NEEDS_AGENT = 76  # likewise, waiting on a delegated agent node


def delegating(environ=None):
    """Read the mode at call time so --delegate can set it before the run."""
    if environ is None:
        environ = os.environ
    return environ.get("WORKFLOW_DELEGATE", "") not in ("", "0")


def _bash(environ=None):
    """Locate a bash that can run step scripts.

    On Windows an unqualified "bash" goes through CreateProcess's search order,
    which checks System32 before PATH — and System32's bash.exe is the WSL
    launcher, which re-tokenizes the command line POSIX-style and cannot see
    Windows drive paths anyway. Prefer Git's bash, which handles them natively.
    """
    if environ is None:
        environ = os.environ
    if os.name != "nt":
        return "bash"
    override = environ.get("WORKFLOW_BASH")
    if override:
        return override
    for base in filter(None, (environ.get("ProgramFiles"),
                              environ.get("ProgramFiles(x86)"))):
        for sub in ("Git/usr/bin/bash.exe", "Git/bin/bash.exe"):
            cand = os.path.join(base, sub)
            if os.path.exists(cand):
                return cand
    found = shutil.which("bash", path=environ.get("PATH", ""))
    if found and "system32" not in found.lower():
        return found
    # No unqualified-"bash" fallback: that silently lands on the WSL launcher
    # again, the same invisible-failure class as a swallowed exception.
    raise SystemExit(
        "no usable bash found for step scripts. Install Git for Windows, or set "
        "WORKFLOW_BASH to a bash that understands Windows paths."
    )


def delegate_agent(prompt, *, node_id, run_dir, model=None, tools=None):
    """Hand one agent node to the operator, or collect what they left.

    One node, split across two invocations. First call writes the composed prompt
    and parks; the next call finds the answer and carries on. The answer is renamed
    rather than deleted, so a retry cannot silently re-consume the reply to an
    earlier attempt, and the run directory still reads as a transcript afterwards.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = run_dir / f"{node_id}.prompt.md"
    result_path = run_dir / f"{node_id}.result.md"

    if result_path.exists():
        text = result_path.read_text(encoding="utf-8").strip()
        consumed = run_dir / f"{node_id}.result.consumed.md"
        consumed.unlink(missing_ok=True)
        result_path.rename(consumed)
        # An empty answer is a failure, not a silent success: it routes down the
        # node's fail edge like any other, rather than passing nothing downstream.
        return Result(bool(text), text or "delegated node returned nothing")

    prompt_path.write_text(prompt, encoding="utf-8")
    spec_note = ""
    if model:
        spec_note = f"This node is specified for model {model}"
        if tools:
            spec_note += f", limited to tools: {', '.join(tools)}"
        spec_note += ".\\n"
    print(
        f"\\n=== {node_id} is delegated ===\\n"
        f"{spec_note}"
        f"Prompt written to : {prompt_path}\\n"
        f"Write the answer to: {result_path}\\n\\n"
        f"Do the work the prompt describes, save the result to that path, then run "
        f"this workflow again with the same --run-dir to continue. Attempt counts "
        f"and the retry ceiling are preserved across the pause.",
        file=sys.stderr,
    )
    raise SystemExit(NEEDS_AGENT)


def run_agent(prompt, *, session_id=None, model=None, tools=None, cwd=None,
              node_id=None, run_dir=None):
    """Invoke an agent as a subprocess and return its result plus session id.

    Resuming matters on retries. A producer that just failed already holds the context
    of what it was attempting; what it lacks is the news that it failed and why.
    Starting a fresh session throws away the former to deliver the latter, and usually
    produces a different first mistake rather than a fix.
    """
    if delegating():
        return delegate_agent(
            prompt, node_id=node_id, run_dir=run_dir, model=model, tools=tools
        )

    cmd = [*AGENT_CLI, "-p", "--output-format", "json", "--permission-mode", PERMISSION_MODE]
    if session_id:
        cmd += ["--resume", session_id]
    if model:
        cmd += ["--model", model]
    if tools:
        cmd += ["--allowed-tools", *tools]

    try:
        # The prompt travels on stdin, not argv. Windows caps a command line at
        # 32767 chars — 8191 through cmd.exe shims, which also truncate at the
        # first newline — and a prompt carrying payload files exceeds that
        # routinely. stdin has no ceiling and no quoting hazards anywhere.
        proc = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True, cwd=cwd,
            timeout=AGENT_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return Result(False, f"agent exceeded {AGENT_TIMEOUT}s timeout", session_id)
    except FileNotFoundError:
        return Result(False, f"the `{AGENT_CLI[0]}` CLI is not on PATH", session_id,
                      launched=False)

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
        # Forward slashes: a backslashed path is mangled by msys bash's own
        # command-line re-parse when launched from a native Windows process.
        proc = subprocess.run(
            [_bash(), str(script).replace(os.sep, "/")], capture_output=True,
            text=True, cwd=cwd, timeout=STEP_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return Result(False, f"step exceeded {STEP_TIMEOUT}s timeout")
    return Result(proc.returncode == 0, (proc.stdout + proc.stderr).strip())


APPROVALS = ("y", "yes", "approve", "approved")
REJECTIONS = ("n", "no", "reject", "rejected")


def read_answer(text):
    """Parse an operator's written answer into (approved, verdict, rationale).

    The first line is the verdict and everything after it is why. An answer
    that is neither an approval nor a rejection is NOT approved: an answer the
    parser does not understand is exactly the case where a person meant
    something specific, and reading consent into it is the one wrong way to
    resolve the ambiguity.
    """
    lines = [line.strip() for line in text.strip().splitlines()]
    verdict = (lines[0] if lines else "").lower().strip(".!,;: ")
    rationale = "\\n".join(lines[1:]).strip()
    if verdict in APPROVALS:
        return True, verdict, rationale
    if verdict in REJECTIONS:
        return False, verdict, rationale
    return False, verdict, text.strip()


def write_decision(run_dir, node_id, *, label, detail, context, approved,
                   verdict, rationale, mode):
    """Record who decided what, and why. A gate nobody can audit is a gesture."""
    record = {
        "node": node_id,
        "label": label,
        "detail": detail,
        "context": str(context),
        "approved": approved,
        "answer": verdict,
        "rationale": rationale,
        "mode": mode,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (Path(run_dir) / f"{node_id}.decision.json").write_text(
        json.dumps(record, indent=2) + "\\n", encoding="utf-8"
    )
    return record


def ask_human(label, detail, context_path, *, node_id="decision"):
    """Get a decision from a person, by whatever route is actually available.

    Three routes, in the order they are tried. Delegate mode parks and reads a
    written answer, which is the only route open to someone driving a workflow
    from inside an assistant with no terminal at all. A real terminal prompts.
    Anything else parks without deciding, because an unattended run that
    approves its own work removes the only check the node existed to provide.
    """
    run_dir = Path(context_path)
    unattended = (
        "No interactive terminal, so this run stops here rather than deciding for "
        "you. Review the context above and rerun with --from to continue."
    )

    if delegating():
        run_dir.mkdir(parents=True, exist_ok=True)
        request_path = run_dir / f"{node_id}.decision.md"
        answer_path = run_dir / f"{node_id}.answer.md"

        if answer_path.exists():
            raw = answer_path.read_text(encoding="utf-8")
            consumed = run_dir / f"{node_id}.answer.consumed.md"
            consumed.unlink(missing_ok=True)
            answer_path.rename(consumed)
            approved, verdict, rationale = read_answer(raw)
            write_decision(
                run_dir, node_id, label=label, detail=detail, context=run_dir,
                approved=approved, verdict=verdict, rationale=rationale,
                mode="delegated",
            )
            return Result(approved, f"human answered: {verdict or 'nothing'}")

        request_path.write_text(
            f"# Decision: {label}\\n\\n{detail}\\n\\n"
            f"Context: {run_dir}\\n\\n---\\n\\n"
            f"Write your answer to `{answer_path.name}` in this directory.\\n\\n"
            f"The first line must be `yes` or `no`. Everything after it is kept as "
            f"your reasoning. An answer that is neither is recorded as not "
            f"approved, so say plainly which you mean.\\n",
            encoding="utf-8",
        )
        print(
            f"\\n=== {label} needs a decision ===\\n{detail}\\n"
            f"Question written to: {request_path}\\n"
            f"Write the answer to : {answer_path}\\n\\n"
            f"First line `yes` or `no`, reasoning after. Then run this workflow "
            f"again with the same --run-dir.",
            file=sys.stderr,
        )
        raise SystemExit(NEEDS_HUMAN)

    print(f"\\n=== {label} ===\\n{detail}\\nContext: {context_path}\\n")
    if not sys.stdin.isatty():
        print(unattended, file=sys.stderr)
        raise SystemExit(NEEDS_HUMAN)
    try:
        answer = input("Approve? [y/N] ").strip().lower()
    except EOFError:
        # A stdin that claims to be a TTY but delivers EOF has nobody at it.
        # Windows does this even for NUL, so isatty alone cannot be trusted.
        print(unattended, file=sys.stderr)
        raise SystemExit(NEEDS_HUMAN)
    approved = answer in APPROVALS
    write_decision(
        run_dir, node_id, label=label, detail=detail, context=context_path,
        approved=approved, verdict=answer or "no", rationale="",
        mode="interactive",
    )
    return Result(approved, f"human answered: {answer or 'no'}")
'''


# ------------------------------------------------------------------ workflow.py

WORKFLOW_HEADER = '''#!/usr/bin/env python3
"""{name} — {goal}

Trigger: {trigger}
Isolation: {isolation}

Generated from spec.json. Regenerating overwrites this file, so put durable edits in
prompts/ and steps/ (never overwritten) or stop regenerating once you take ownership.

Run:
    python3 workflow.py                 # full run, agents via the agent CLI
    python3 workflow.py --delegate      # full run, agents done by you
    python3 workflow.py --only build    # one node, against the last run's payloads
    python3 workflow.py --from verify   # resume partway

Exit codes:
    0   reached a terminal node
    1   a node failed with nowhere to route, or exhausted its retries
    2   operator error, such as an unknown node passed to --only
    75  parked: a human node was reached with nobody watching
    76  parked: a delegated agent node is waiting for its answer
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from runner import Result, ask_human, delegating, run_agent, run_step

HERE = Path(__file__).parent
ENTRY = {entry!r}

# Ceiling on agent calls for the whole run, or None for no ceiling. Per-node
# max_attempts cannot see across nodes, so two nodes on a loop edge can each
# honour their own bound and still ping-pong indefinitely. This counts the run.
BUDGET_AGENT_CALLS = {budget!r}

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
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def write(self, name: str, text: str) -> None:
        path = self.run_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def prompt_for(self, node_id: str) -> str:
        """Fill a prompt template with the payloads this node declares it reads."""
        template = (HERE / "prompts" / f"{node_id}.md").read_text(encoding="utf-8")
        # Authoring notes are for whoever maintains the prompt, not for the model.
        template = re.sub(r"<!--.*?-->", "", template, flags=re.DOTALL)
        for name in NODES[node_id].get("reads", []):
            template = template.replace("{{" + name + "}}", self.read(name))
        template = template.replace("{{feedback}}", self.feedback or "")
        return template.strip()


def check_evidence(node, ctx: Context):
    """Return what is missing, or None when the node left proof it worked.

    The bar is that the named artifact exists and is not empty. That catches
    the silent no-op — the node that reported success and produced nothing —
    which is the common failure. It does not catch a node that writes a token
    file to satisfy the check, and it is not meant to: the point is to stop a
    claim from travelling downstream unaccompanied, not to grade the artifact.
    """
    name = node.get("evidence")
    if not name:
        return None
    path = ctx.run_dir / name
    if not path.exists():
        return f"declared evidence '{name}' but produced no such file ({path})"
    if not path.read_text(encoding="utf-8", errors="replace").strip():
        return f"declared evidence '{name}' but the file is empty"
    return None


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
            node_id=node_id,
            run_dir=ctx.run_dir,
        )
        if result.session_id:
            ctx.sessions[node_id] = result.session_id
        return result

    if kind == "human":
        return ask_human(node["label"], node.get("detail", ""), ctx.run_dir,
                         node_id=node_id)

    return Result(False, f"unknown node kind: {kind}")


ESCALATION_MODEL = "opus"

# A bound only means something for nodes a failure edge loops back into — those are
# the ones that can be re-entered indefinitely. A checker that fails is doing its job,
# not consuming a retry of its own. Human nodes are excluded for the same reason the
# validator does not demand a bound on them: reaching one costs a person's attention
# and stops the run until they act, so it cannot run away unattended.
RETRY_TARGETS = {e["to"] for e in EDGES
                 if e.get("when") == "fail" and NODES[e["to"]].get("kind") != "human"}


def give_up(node_id: str, ctx: Context, limit: int) -> int:
    node = NODES[node_id]
    action = node.get("on_exhausted", "fail")
    log(f"  {node_id}: giving up after {limit} attempt(s) -> {action}")
    if action == "human":
        outcome = ask_human(
            f"{node_id} could not be completed automatically",
            node.get("detail", ""),
            ctx.run_dir,
            node_id=node_id,
        )
        return 0 if outcome.ok else 1
    return 1


STATE_FILE = "driver-state.json"
FINAL_STATE_FILE = "driver-state.final.json"


def save_state(ctx: Context, current: str, attempts: dict[str, int],
               spend: int = 0) -> None:
    """Record where the driver is, so a pause can be resumed exactly.

    Only delegate mode pauses mid-run, but the state is cheap and writing it
    unconditionally means a crashed subprocess run also leaves a readable record
    of which node it died on and how many attempts it had spent.
    """
    (ctx.run_dir / STATE_FILE).write_text(
        json.dumps(
            {"current": current, "attempts": dict(attempts),
             "feedback": ctx.feedback, "agent_calls_spent": spend},
            indent=2,
        ),
        encoding="utf-8",
    )


def load_state(ctx: Context):
    """Return (current, attempts, feedback, spend) from a paused run, or None."""
    path = ctx.run_dir / STATE_FILE
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not data.get("current"):
        return None
    return (data["current"], defaultdict(int, data.get("attempts", {})),
            data.get("feedback"), data.get("agent_calls_spent", 0))


def clear_state(ctx: Context) -> None:
    """Retire the state file so a finished run cannot resume itself.

    Renamed rather than deleted. Stopping the resume needs the live name gone,
    which a rename achieves — and deleting it would throw away the one record
    of what the run cost: how many attempts each node took and how much budget
    it spent. That is exactly the receipt worth keeping for a run that
    succeeded, which is the case a delete was silently discarding.
    """
    live = ctx.run_dir / STATE_FILE
    if not live.exists():
        return
    final = ctx.run_dir / FINAL_STATE_FILE
    final.unlink(missing_ok=True)
    live.rename(final)


def budget_handoff(node_id: str, ctx: Context, spend: int) -> int:
    """Stop between nodes and hand the situation to a person.

    Deliberately not a failure. The run did nothing wrong; it reached a ceiling
    someone set on purpose, and the only way past is a person deciding the work
    is worth more than the ceiling says.
    """
    outcome = ask_human(
        f"Run budget spent before {node_id}",
        f"This run has used its whole budget of {BUDGET_AGENT_CALLS} agent "
        f"call(s) and stopped before launching another. To continue, raise "
        f"budget.agent_calls in spec.json, regenerate, and start a fresh run.",
        ctx.run_dir,
        node_id=node_id,
    )
    return 0 if outcome.ok else 1


def drive(ctx: Context, start: str) -> int:
    attempts: dict[str, int] = defaultdict(int)
    current = start
    spend = 0
    # A delegated run resumes where it parked. The attempt that parked was
    # already counted, so the first pass through the loop must not count it
    # again — otherwise every pause would burn a retry and a three-attempt
    # ceiling would be reached in two.
    resuming = False
    if delegating():
        saved = load_state(ctx)
        if saved:
            current, attempts, ctx.feedback, spend = saved
            resuming = True
            log(f"resuming at {current} (attempt {attempts[current]})")

    while current:
        node = NODES[current]
        if resuming:
            resuming = False
        else:
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
                clear_state(ctx)
                return give_up(current, ctx, limit)

        # Checked before the call so an exhausted budget never launches one.
        if (node["kind"] == "agent" and BUDGET_AGENT_CALLS is not None
                and spend >= BUDGET_AGENT_CALLS):
            log(f"  {current}: run budget of {BUDGET_AGENT_CALLS} agent "
                f"call(s) is spent — stopping before this one")
            return budget_handoff(current, ctx, spend)

        suffix = f" (attempt {attempts[current]}/{limit})" if bounded else ""
        log(f"{current} [{node['kind']}] {node['label']}{suffix}")

        # Written before the node runs, because a delegated node exits the
        # process from inside run_node and this is what it resumes from.
        save_state(ctx, current, attempts, spend)

        result = run_node(current, ctx)
        # Charged on return, whatever the outcome: a call that launched and then
        # errored or timed out has already cost money, so only crediting
        # successes would let a crash-looping node spend without moving the
        # counter. Two things never return here and so are never charged — a
        # missing CLI (launched is False) and a delegated park, which exits the
        # process before any model runs.
        if node["kind"] == "agent" and result.launched:
            spend += 1
        ctx.write(f"{current}.out", result.output)
        ctx.feedback = None

        # Only an otherwise-successful node is asked for proof. One that already
        # failed has a real reason, and replacing it with a missing-artifact
        # complaint would bury the useful one. Checked before any edge is
        # followed, so it gates `always` traversals as much as `pass` ones —
        # gating only `pass` would leave most real workflows unchecked.
        if result.ok:
            shortfall = check_evidence(node, ctx)
            if shortfall:
                log(f"  {current}: {shortfall}")
                result = Result(False, f"{current} {shortfall}", result.session_id)

        if result.ok:
            edge = next_node(current, ("always", "pass"))
            if edge is None:
                log(f"done — {current} was terminal")
                clear_state(ctx)
                return 0
            if edge.get("payload") and result.output:
                ctx.write(edge["payload"], result.output)
            current = edge["to"]
            continue

        log(f"  failed: {result.output[:300]}")

        edge = next_node(current, ("fail",))
        if edge is None:
            # Nothing to route to, so this failure ends the run.
            clear_state(ctx)
            return give_up(current, ctx, limit)

        if edge.get("payload"):
            ctx.write(edge["payload"], result.output)
        # A loop edge carries the failure back as feedback rather than as a fresh task.
        ctx.feedback = result.output if edge.get("loop") else None
        current = edge["to"]

    clear_state(ctx)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", default=str(HERE / "runs" / "latest"),
                    help="where payloads live")
    ap.add_argument("--workdir", default=".", help="where code and agents execute")
    ap.add_argument("--only", help="run a single node against existing payloads")
    ap.add_argument("--from", dest="start", help="start partway through")
    ap.add_argument(
        "--delegate",
        action="store_true",
        help="do agent nodes yourself instead of spawning an agent CLI: the run "
             "parks at each one, writes the prompt, and resumes when you leave "
             "the answer beside it (same as WORKFLOW_DELEGATE=1)",
    )
    args = ap.parse_args()

    if args.delegate:
        # Set before anything reads it, so --delegate and the environment
        # variable are genuinely the same switch rather than two code paths.
        os.environ["WORKFLOW_DELEGATE"] = "1"

    ctx = Context(Path(args.run_dir), Path(args.workdir).resolve())

    if args.only:
        if args.only not in NODES:
            print(f"unknown node: {args.only}", file=sys.stderr)
            return 2
        result = run_node(args.only, ctx)
        ctx.write(f"{args.only}.out", result.output)
        print(result.output)
        return 0 if result.ok else 1

    if args.start:
        # An explicit starting point overrides a parked run rather than being
        # silently ignored in favour of the saved position.
        clear_state(ctx)

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
- `WORKFLOW_AGENT_CLI` (default `claude`; may carry arguments, e.g. a stub for tests)
- `WORKFLOW_BASH` (Windows only: which bash runs the step scripts)

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
    (out / "runner.py").write_text(RUNNER, encoding="utf-8")
    (out / "workflow.py").write_text(
        WORKFLOW_HEADER.format(
            name=spec["name"],
            goal=spec["goal"],
            trigger=spec["trigger"],
            isolation=spec.get("isolation", "none"),
            entry=spec["entry"],
            budget=(spec.get("budget") or {}).get("agent_calls"),
            # pprint, not json.dumps: JSON's true/false/null are bare names in
            # Python and would blow up at import rather than at compile time.
            nodes=pprint.pformat(nodes, indent=4, sort_dicts=False, width=88),
            edges=pprint.pformat(spec["edges"], indent=4, sort_dicts=False, width=88),
        )
        + WORKFLOW_BODY,
        encoding="utf-8",
    )
    (out / "workflow.py").chmod(0o755)
    (out / "spec.json").write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")

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
        path.write_text(body, encoding="utf-8")
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
        ),
        encoding="utf-8",
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
