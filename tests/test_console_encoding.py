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
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from helpers import EXAMPLE_SPEC, REPO, tmpdir

# Calls whose arguments land on a console rather than in a file.
CONSOLE_CALLS = {"print", "exit", "SystemExit"}

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


def console_strings(path):
    """Yield (lineno, text) for every literal handed to a console call.

    Walks f-strings too: their literal segments are where the decoration
    actually hides, since the interpolated values are usually paths and counts.
    """
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _callee(node) not in CONSOLE_CALLS:
            continue
        for arg in node.args:
            for sub in ast.walk(arg):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    yield node.lineno, sub.value


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


if __name__ == "__main__":
    unittest.main()
