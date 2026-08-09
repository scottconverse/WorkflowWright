"""`--report`: say what the event logs already know, and change nothing.

The driver has written run.jsonl for a while and never read it back, so every run
started amnesiac about every run before it. This closes that loop in the one
direction that stays honest -- reporting. The same numbers would drive an automatic
model choice, and deliberately do not: a run that silently re-routes itself is a
different kind of program, and the decision about a node failing eight times in ten
stays a person's.
"""

import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from helpers import make_stub_claude, run_workflow, tmpdir, valid_spec, write_spec
from test_scaffold import scaffold


class ReportCase(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tmpdir())
        self.addCleanup(shutil.rmtree, self.dir, True)

    def build(self, spec, steps=None):
        pkg = self.dir / "pkg"
        proc = scaffold(write_spec(self.dir, spec), pkg)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for node_id, body in (steps or {}).items():
            (pkg / "steps" / f"{node_id}.sh").write_text(body, encoding="utf-8")
        return pkg

    def report(self, pkg, *args):
        proc = subprocess.run(
            [sys.executable, str(pkg / "workflow.py"), "--report", *args],
            capture_output=True, text=True, cwd=pkg, timeout=120,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return proc.stdout


class NoRunsYet(ReportCase):
    def test_says_so_instead_of_failing(self):
        pkg = self.build(valid_spec())
        self.assertIn("no runs found", self.report(pkg))


class AcrossRuns(ReportCase):
    """The point of the feature: one run cannot tell you a node is unreliable."""

    def spec(self):
        spec = valid_spec()
        spec["nodes"][0]["backend"] = "claude"
        return spec

    def run_twice(self, pkg, agent_cli):
        for name in ("one", "two"):
            run_workflow(pkg, self.dir / "runs" / name, workdir=pkg,
                         agent_cli=agent_cli)

    def test_counts_attempts_across_every_run_directory(self):
        pkg = self.build(self.spec(), steps={"check": "exit 0\n", "ship": "exit 0\n"})
        self.run_twice(pkg, make_stub_claude(self.dir / "stub"))

        out = self.report(pkg, "--runs", str(self.dir / "runs"))

        self.assertIn("2 run(s)", out)
        self.assertIn("make", out)

    def test_groups_a_node_by_the_backend_it_ran_on(self):
        """Which backend a node failed on is the whole reason to group at all."""
        spec = self.spec()
        spec["nodes"][0]["backend"] = "codex"
        pkg = self.build(spec, steps={"check": "exit 0\n", "ship": "exit 0\n"})
        # No codex stub: the node fails because the CLI is absent, which is a real
        # scenario and enough for this test. The backend is recorded at node_start,
        # before the call, so it is known whether or not the call ever happens --
        # which is exactly what makes the grouping trustworthy when a backend is
        # failing.
        run_workflow(pkg, self.dir / "runs" / "one", workdir=pkg)

        out = self.report(pkg, "--runs", str(self.dir / "runs"))
        self.assertIn("codex", out)

    def test_flags_a_node_that_fails_more_than_it_succeeds(self):
        """Three attempts is the floor for saying anything; below that it is noise."""
        spec = self.spec()
        spec["nodes"][0]["max_attempts"] = 3
        pkg = self.build(spec, steps={"check": "echo nope; exit 1\n",
                                      "ship": "exit 0\n"})
        stub = make_stub_claude(self.dir / "stub")
        self.run_twice(pkg, stub)

        out = self.report(pkg, "--runs", str(self.dir / "runs"))

        # The whole sentence, not its words: "of" and "failed" appear in the
        # report's own prose whatever the numbers are, so asserting on them
        # passes even when nothing was flagged.
        self.assertRegex(out, r"note: check on \S+ failed \d+ of \d+ attempts "
                              r"across \d+ run\(s\)\.")

    def test_a_line_that_parses_but_is_not_a_record_does_not_stop_the_report(self):
        """Valid JSON is not the same as a record, and the difference crashed it.

        A line holding a list, a bare string, a number or a null parses cleanly
        and then fails on the line that stamps the run name onto it; a node or
        backend arriving as a list fails later still, on "unhashable type". Eight
        shapes in all, every one of them a traceback out of the function whose
        docstring promises to survive a damaged log -- and since this reads every
        run beneath the root, one bad line in one stale directory took the report
        for every other run with it.
        """
        pkg = self.build(self.spec(), steps={"check": "exit 0\n", "ship": "exit 0\n"})
        runs = self.dir / "runs"
        run_workflow(pkg, runs / "good", workdir=pkg,
                     agent_cli=make_stub_claude(self.dir / "stub"))

        junk = runs / "damaged"
        junk.mkdir(parents=True, exist_ok=True)
        (junk / "run.jsonl").write_text(
            '[1,2,3]\n'
            '"a string"\n'
            '42\n'
            'null\n'
            'true\n'
            '{"event":"node_result","node":["a"],"ok":true}\n'
            '{"event":"node_result","node":{"x":1},"ok":true}\n'
            '{"event":"node_start","node":"a","backend":["x"]}\n',
            encoding="utf-8")

        out = self.report(pkg, "--runs", str(runs))

        # The good run is still reported, which is the point: one damaged file
        # must not cost the information in every other one.
        self.assertIn("make", out)

    def test_a_truncated_log_does_not_stop_the_report(self):
        """A killed run leaves a half-written last line. That is exactly when
        somebody wants the report, so it must not be what prevents it."""
        pkg = self.build(self.spec(), steps={"check": "exit 0\n", "ship": "exit 0\n"})
        self.run_twice(pkg, make_stub_claude(self.dir / "stub"))
        log = self.dir / "runs" / "one" / "run.jsonl"
        with log.open("a", encoding="utf-8") as handle:
            handle.write('{"event": "node_res')

        self.assertIn("run(s)", self.report(pkg, "--runs", str(self.dir / "runs")))


class ReportChangesNothing(ReportCase):
    def test_it_neither_starts_nor_resumes_a_run(self):
        """--report is read-only. It must not create a run directory, advance a
        parked run, or write a single event of its own."""
        pkg = self.build(valid_spec(), steps={"check": "exit 0\n", "ship": "exit 0\n"})
        runs = self.dir / "runs"
        run_workflow(pkg, runs / "one", workdir=pkg,
                     agent_cli=make_stub_claude(self.dir / "stub"))
        log = runs / "one" / "run.jsonl"
        before = log.read_bytes()
        listing_before = sorted(p.name for p in runs.iterdir())

        self.report(pkg, "--runs", str(runs))

        self.assertEqual(log.read_bytes(), before, "the report wrote to the log")
        self.assertEqual(sorted(p.name for p in runs.iterdir()), listing_before)
        self.assertFalse((pkg / "runs" / "latest").exists(),
                         "the report created a default run directory")


if __name__ == "__main__":
    unittest.main()
