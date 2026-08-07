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
    path.write_text(json.dumps(spec, indent=2))
    return path


def make_stub_claude(directory, responses=None, fail_until=0):
    """A fake `claude` CLI that records argv and emits the real JSON output shape.

    Lets the driver's agent path be exercised without network, cost, or credentials.
    Every invocation appends its full argv to calls.log and its prompt to prompts.log,
    so tests can assert on flags like --resume and on prompt substitution.
    """
    directory = Path(directory)
    bindir = directory / "bin"
    bindir.mkdir(parents=True, exist_ok=True)
    script = bindir / "claude"
    script.write_text(
        "#!/usr/bin/env bash\n"
        f'log="{directory}"\n'
        "# Log flags only, one line per invocation. The prompt is multi-line, so\n"
        "# including it would make line offsets meaningless for callers.\n"
        'printf "%s\\n" "${*:1:$#-1}" >> "$log/calls.log"\n'
        'prompt="${@: -1}"\n'
        'printf "%s\\n---CALL---\\n" "$prompt" >> "$log/prompts.log"\n'
        'n=$(cat "$log/n" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "$log/n"\n'
        f'if [ "$n" -le {fail_until} ]; then\n'
        '  printf \'{"session_id":"sess-1","is_error":true,"result":"agent failed"}\'\n'
        "  exit 0\n"
        "fi\n"
        'printf \'{"session_id":"sess-1","is_error":false,"result":"output %s"}\' "$n"\n'
    )
    script.chmod(0o755)
    return bindir


def run_workflow(pkg, run_dir, workdir=None, extra_path=None, args=()):
    """Execute a generated workflow package and return (returncode, combined output)."""
    env = dict(os.environ)
    if extra_path:
        env["PATH"] = f"{extra_path}:{env['PATH']}"
    cmd = [
        sys.executable,
        str(Path(pkg) / "workflow.py"),
        "--run-dir",
        str(run_dir),
        "--workdir",
        str(workdir or pkg),
        *args,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=pkg, env=env)
    return proc.returncode, proc.stdout + proc.stderr


def tmpdir():
    return tempfile.mkdtemp(prefix="awa-test-")
