"""Shared fixtures for the test suite.

The scripts under test live in skill/scripts/ and are imported directly rather than
shelled out to, so failures surface as tracebacks instead of exit codes.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "skill" / "scripts"
EXAMPLE_SPEC = REPO / "skill" / "assets" / "example-spec.json"

sys.path.insert(0, str(SCRIPTS))


def valid_spec():
    """A minimal spec that passes validation, for tests to mutate into invalid ones."""
    return {
        "name": "fixture",
        "goal": "A spec that validates cleanly",
        "trigger": "manual",
        "isolation": "none",
        "entry": "make",
        "nodes": [
            {
                "id": "make",
                "label": "Make it",
                "kind": "agent",
                "detail": "produce the thing",
                "model": "sonnet",
                "max_attempts": 3,
                "on_exhausted": "fail",
            },
            {"id": "check", "label": "Check it", "kind": "code", "detail": "verify"},
            {"id": "ship", "label": "Ship it", "kind": "human", "detail": "approve"},
        ],
        "edges": [
            {"from": "make", "to": "check", "when": "always", "payload": "artifact"},
            {"from": "check", "to": "ship", "when": "pass", "payload": "artifact"},
            {
                "from": "check",
                "to": "make",
                "when": "fail",
                "payload": "report.txt",
                "loop": True,
            },
        ],
        "open_questions": [],
    }


def write_spec(directory, spec):
    path = Path(directory) / "spec.json"
    path.write_text(json.dumps(spec, indent=2), encoding="utf-8")
    return path


def make_stub_claude(directory, responses=None, fail_until=0):
    """A fake `claude` CLI that records argv and emits the real JSON output shape.

    Lets the driver's agent path be exercised without network, cost, or credentials.
    Every invocation appends its flags to calls.log and its prompt to prompts.log,
    so tests can assert on flags like --resume and on prompt substitution.

    Written in Python and injected via WORKFLOW_AGENT_CLI rather than a shell
    script on PATH: Windows cannot execute an extensionless shebang script, and
    with the stub unlaunchable, PATH resolution would fall through to a real
    `claude` installation — spending actual tokens from inside the test suite.
    Returns the WORKFLOW_AGENT_CLI value that routes the driver to the stub.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / "claude_stub.py"
    script.write_text(
        "import sys\n"
        "from pathlib import Path\n"
        "log = Path(__file__).resolve().parent\n"
        "flags, prompt = sys.argv[1:], sys.stdin.read()\n"
        "# Log flags only, one line per invocation. The prompt is multi-line, so\n"
        "# including it would make line offsets meaningless for callers.\n"
        'with (log / "calls.log").open("a", encoding="utf-8") as f:\n'
        '    f.write(" ".join(flags) + "\\n")\n'
        'with (log / "prompts.log").open("a", encoding="utf-8") as f:\n'
        '    f.write(prompt + "\\n---CALL---\\n")\n'
        'n_path = log / "n"\n'
        'n = int(n_path.read_text(encoding="utf-8")) + 1 if n_path.exists() else 1\n'
        'n_path.write_text(str(n), encoding="utf-8")\n'
        f"if n <= {fail_until}:\n"
        '    print(\'{"session_id":"sess-1","is_error":true,"result":"agent failed"}\', end="")\n'
        "else:\n"
        '    print(\'{"session_id":"sess-1","is_error":false,"result":"output %d"}\' % n, end="")\n',
        encoding="utf-8",
    )
    # Forward slashes keep the value safe through shlex.split on every platform.
    return f'"{sys.executable}" "{script}"'.replace(os.sep, "/")


def run_workflow(pkg, run_dir, workdir=None, agent_cli=None, args=(), delegate=False):
    """Execute a generated workflow package and return (returncode, combined output)."""
    env = dict(os.environ)
    if agent_cli:
        env["WORKFLOW_AGENT_CLI"] = agent_cli
    if delegate:
        env["WORKFLOW_DELEGATE"] = "1"
    cmd = [
        sys.executable,
        str(Path(pkg) / "workflow.py"),
        "--run-dir",
        str(run_dir),
        "--workdir",
        str(workdir or pkg),
        *args,
    ]
    # stdin detached: "unattended" must mean no stdin, and on Windows the
    # inherited console handle passes isatty() even with nobody at it.
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=pkg, env=env,
                          stdin=subprocess.DEVNULL)
    return proc.returncode, proc.stdout + proc.stderr


def tmpdir():
    return tempfile.mkdtemp(prefix="awa-test-")
