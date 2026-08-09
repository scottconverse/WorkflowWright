"""Anything printed must survive a console encoding we do not get to choose.

Files are ours: everything written to disk is opened with encoding="utf-8", so
an em dash in a document is safe and stays. The console is not ours. cmd.exe
defaults to cp437, which has no em dash, and `print` of one raises
UnicodeEncodeError — usually partway through, after the work has been done,
replacing the message that explains what happened with a traceback about a
character.

So the rule is narrow on purpose: prose and comments keep their punctuation,
and only strings that reach stdout or stderr are held to ASCII. This checks the
scripts in the repo and, separately, the code they generate — a generated
runner's prints live inside a string literal here, where no parse of this repo
would ever see them.
"""

import ast
import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from helpers import EXAMPLE_SPEC, REPO, tmpdir, write_spec
from test_scaffold import loop_spec, scaffold

# Calls whose arguments land on a console rather than in a file. `log` is the
# generated driver's own print wrapper: leaving it out is how an em dash reached
# the success path of every run and crashed it on cmd.exe while this file was
# green. A wrapper is the normal way a print gets written, so the set has to name
# them.
CONSOLE_CALLS = {"print", "exit", "SystemExit", "log"}

# Functions that build a string for something else to print. Their returns and
# appends never appear as an argument to a console call, so the AST walk below
# cannot reach them -- yet validate()'s problems are printed verbatim by both
# scripts' main(). Named explicitly rather than inferred, because guessing which
# strings escape a function is a data-flow analysis and this is a test.
CONSOLE_PRODUCERS = {"validate"}

SCRIPTS = [
    REPO / "skill" / "scripts" / "render_workflow.py",
    REPO / "skill" / "scripts" / "scaffold_workflow.py",
    REPO / "scripts" / "build_package.py",
    REPO / "scripts" / "uninstall.py",
    REPO / "docs" / "build_site.py",
]


def _callee(node):
    """print(...) and sys.exit(...) both matter; spell out either shape."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _literals(node):
    """Every string literal anywhere under an AST node.

    Walks f-strings too: their literal segments are where the decoration
    actually hides, since the interpolated values are usually paths and counts.
    """
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            yield sub


def console_strings(path):
    """Yield (lineno, text) for every literal that can reach a console.

    Two routes, because there are two ways a string gets printed: handed to a
    console call directly, or built inside a function whose whole output is
    printed by somebody else.
    """
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _callee(node) in CONSOLE_CALLS:
            for arg in node.args:
                for sub in _literals(arg):
                    yield node.lineno, sub.value
        elif (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name in CONSOLE_PRODUCERS):
            # The docstring is prose about the function, not output from it.
            body = node.body[1:] if ast.get_docstring(node) else node.body
            for statement in body:
                for sub in _literals(statement):
                    yield sub.lineno, sub.value


def offenders(path):
    return [(line, text) for line, text in console_strings(path)
            if any(ord(ch) > 127 for ch in text)]


class ConsoleOutputIsAscii(unittest.TestCase):
    def test_repo_scripts_print_only_ascii(self):
        found = {}
        for script in SCRIPTS:
            bad = offenders(script)
            if bad:
                found[script.relative_to(REPO).as_posix()] = bad

        self.assertEqual(
            found, {},
            "these printed strings die on a cp437 console; use ASCII in output "
            f"(comments and docs are fine): {found}")

    def test_generated_package_prints_only_ascii(self):
        """The generated runner is a string literal here, so parsing this repo
        cannot see its prints. Generate a real package and parse that instead."""
        out = Path(tmpdir())
        self.addCleanup(shutil.rmtree, out, True)
        proc = subprocess.run(
            [sys.executable, str(REPO / "skill" / "scripts" / "scaffold_workflow.py"),
             str(EXAMPLE_SPEC), "--out", str(out / "pkg")],
            capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

        found = {}
        for generated in sorted((out / "pkg").glob("*.py")):
            bad = offenders(generated)
            if bad:
                found[generated.name] = bad

        self.assertEqual(
            found, {},
            f"a generated workflow would crash on a cp437 console: {found}")


class ARunSurvivesACp437Console(unittest.TestCase):
    """The dynamic half. Static analysis found none of this on its own.

    Two holes let an em dash reach the success path of every generated run: the
    call was a print wrapper rather than a print, and nothing here had ever
    executed generated code on a console that could not encode it. This does,
    and it checks the consequences rather than only the exit status -- the throw
    landed between the last node finishing and the two lines that record the run
    as over, so a crash here also means a finished run stays resumable.
    """

    def test_a_successful_run_ends_cleanly_when_stdout_is_cp437(self):
        work = Path(tmpdir())
        self.addCleanup(shutil.rmtree, work, True)
        pkg = work / "pkg"
        proc = scaffold(write_spec(work, loop_spec()), pkg)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for name, body in {"work": "echo working\n", "check": "exit 0\n",
                           "ship": "echo shipped\n"}.items():
            (pkg / "steps" / f"{name}.sh").write_text(body, encoding="utf-8")

        run_dir = work / "run"
        # cp437 is what cmd.exe hands a process by default. Not :strict -- the
        # point is to reproduce the console a user actually has, and stdout is
        # already strict there without being asked.
        env = dict(os.environ, PYTHONIOENCODING="cp437")
        run = subprocess.run(
            [sys.executable, str(pkg / "workflow.py"), "--run-dir", str(run_dir),
             "--workdir", str(pkg)],
            capture_output=True, text=True, cwd=pkg, env=env,
            stdin=subprocess.DEVNULL, timeout=180,
        )

        self.assertEqual(run.returncode, 0,
                         "a completed run reported failure:\n" + run.stderr)
        self.assertNotIn("UnicodeEncodeError", run.stderr)

        events = [json.loads(line) for line
                  in (run_dir / "run.jsonl").read_text(encoding="utf-8").splitlines()
                  if line.strip()]
        self.assertTrue(any(e["event"] == "run_end" for e in events),
                        "the run ended without recording that it ended")
        self.assertTrue((run_dir / "driver-state.final.json").is_file(),
                        "no receipt: the finished run kept no record of its cost")
        self.assertFalse((run_dir / "driver-state.json").exists(),
                         "a finished run left itself resumable")


if __name__ == "__main__":
    unittest.main()
