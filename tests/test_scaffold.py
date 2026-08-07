"""Scaffolding and the generated driver's runtime behaviour.

The driver tests matter most: retry accounting and session resume are the two things
that are easy to get subtly wrong by hand, and both were wrong in an early version of
this generator. They are exercised here against a stub CLI, so no credentials, network,
or token spend is involved.
"""

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from helpers import (EXAMPLE_SPEC, SCRIPTS, make_stub_claude, run_workflow, tmpdir,
                     valid_spec, write_spec)


def scaffold(spec_path, out, *args):
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "scaffold_workflow.py"), str(spec_path),
         "--out", str(out), *args],
        capture_output=True, text=True,
    )


def loop_spec():
    """Producer/checker pair with a bounded loop — the atom every workflow is built from."""
    return {
        "name": "loop", "goal": "exercise the loop", "trigger": "manual",
        "isolation": "none", "entry": "work",
        "nodes": [
            {"id": "work", "label": "Work", "kind": "code", "detail": "increments",
             "max_attempts": 3, "on_exhausted": "fail"},
            {"id": "check", "label": "Check", "kind": "code", "detail": "verifies"},
            {"id": "ship", "label": "Ship", "kind": "code", "detail": "final"},
        ],
        "edges": [
            {"from": "work", "to": "check", "when": "always", "payload": "work.log"},
            {"from": "check", "to": "ship", "when": "pass", "payload": "work.log"},
            {"from": "check", "to": "work", "when": "fail", "payload": "report.txt",
             "loop": True},
        ],
        "open_questions": [],
    }


class ScaffoldCase(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tmpdir())

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def build(self, spec, steps=None):
        pkg = self.dir / "pkg"
        proc = scaffold(write_spec(self.dir, spec), pkg)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for node_id, body in (steps or {}).items():
            (pkg / "steps" / f"{node_id}.sh").write_text(body)
        return pkg


class TestGeneration(ScaffoldCase):
    def test_refuses_structurally_broken_spec(self):
        """Cheaper to fix an unbounded loop in the spec than in generated code."""
        spec = valid_spec()
        spec["nodes"][0].pop("max_attempts")
        proc = scaffold(write_spec(self.dir, spec), self.dir / "pkg")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("refusing to scaffold", proc.stderr)
        self.assertFalse((self.dir / "pkg" / "workflow.py").exists())

    def test_generates_one_artifact_per_node(self):
        pkg = self.build(valid_spec())
        self.assertTrue((pkg / "prompts" / "make.md").exists())
        self.assertTrue((pkg / "steps" / "check.sh").exists())
        self.assertFalse((pkg / "steps" / "ship.sh").exists(), "human nodes need no script")

    def test_generated_module_imports(self):
        """Regression: json.dumps emits true/false/null, which are valid Python *names*.
        py_compile therefore passes and the module explodes at import instead."""
        pkg = self.build(EXAMPLE_SPEC and json.loads(Path(EXAMPLE_SPEC).read_text()))
        proc = subprocess.run(
            [sys.executable, "-c",
             f"import sys; sys.path.insert(0, {str(pkg)!r}); import workflow; "
             "print(len(workflow.NODES), sorted(workflow.RETRY_TARGETS))"],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("7 ['build']", proc.stdout)

    def test_regeneration_preserves_hand_written_work(self):
        spec = valid_spec()
        pkg = self.build(spec)
        (pkg / "prompts" / "make.md").write_text("MY PROMPT")
        (pkg / "steps" / "check.sh").write_text("MY STEP")
        proc = scaffold(write_spec(self.dir, spec), pkg)
        self.assertIn("kept", proc.stdout)
        self.assertEqual((pkg / "prompts" / "make.md").read_text(), "MY PROMPT")
        self.assertEqual((pkg / "steps" / "check.sh").read_text(), "MY STEP")

    def test_force_overwrites(self):
        spec = valid_spec()
        pkg = self.build(spec)
        (pkg / "prompts" / "make.md").write_text("MY PROMPT")
        scaffold(write_spec(self.dir, spec), pkg, "--force")
        self.assertNotEqual((pkg / "prompts" / "make.md").read_text(), "MY PROMPT")

    def test_steps_start_as_honest_failures(self):
        """A stub that exits 0 would let an empty workflow report success."""
        pkg = self.build(valid_spec())
        self.assertIn("exit 1", (pkg / "steps" / "check.sh").read_text())


class TestRetryAccounting(ScaffoldCase):
    """Regression: attempts were counted against the node that *failed* (the checker)
    rather than the node the failure edge *re-enters* (the producer). Counted that way,
    the first check failure exhausted the loop immediately."""

    COUNTER = 'n=$(cat "$PWD/counter" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "$PWD/counter"; echo "attempt $n"\n'

    def test_loop_converges(self):
        pkg = self.build(loop_spec(), steps={
            "work": self.COUNTER,
            "check": 'n=$(cat "$PWD/counter"); [ "$n" -ge 3 ] && { echo pass; exit 0; }; echo "too few"; exit 1\n',
            "ship": "echo shipped\n",
        })
        code, out = run_workflow(pkg, self.dir / "run", workdir=pkg)
        self.assertEqual(code, 0, out)
        self.assertEqual(out.count("work [code]"), 3, out)
        self.assertIn("shipped", (self.dir / "run" / "ship.out").read_text())

    def test_checker_failing_repeatedly_does_not_consume_its_own_retries(self):
        pkg = self.build(loop_spec(), steps={
            "work": self.COUNTER,
            "check": 'n=$(cat "$PWD/counter"); [ "$n" -ge 2 ] && exit 0; exit 1\n',
            "ship": "echo shipped\n",
        })
        code, out = run_workflow(pkg, self.dir / "run", workdir=pkg)
        self.assertEqual(code, 0, out)

    def test_exhaustion_is_bounded_exactly(self):
        pkg = self.build(loop_spec(), steps={
            "work": self.COUNTER,
            "check": 'echo "never passes"; exit 1\n',
            "ship": "echo shipped\n",
        })
        code, out = run_workflow(pkg, self.dir / "run", workdir=pkg)
        self.assertEqual(code, 1)
        self.assertEqual(out.count("work [code]"), 3, "max_attempts=3 must mean 3 runs")
        self.assertIn("giving up after 3", out)

    def test_failure_payload_is_written_for_the_producer(self):
        pkg = self.build(loop_spec(), steps={
            "work": self.COUNTER,
            "check": 'echo "REJECTED: specific reason"; exit 1\n',
            "ship": "echo shipped\n",
        })
        run_workflow(pkg, self.dir / "run", workdir=pkg)
        self.assertIn("REJECTED: specific reason",
                      (self.dir / "run" / "report.txt").read_text())


class TestAgentInvocation(ScaffoldCase):
    def agent_spec(self):
        return {
            "name": "agenty", "goal": "exercise agent nodes", "trigger": "manual",
            "isolation": "none", "entry": "gen",
            "nodes": [
                {"id": "gen", "label": "Generate", "kind": "agent", "detail": "make it",
                 "model": "sonnet", "tools": ["Read", "Write"],
                 "reads": ["brief.md"], "writes": ["draft.txt"],
                 "max_attempts": 3, "on_exhausted": "fail"},
                {"id": "judge", "label": "Judge", "kind": "code", "detail": "checks"},
                {"id": "ship", "label": "Ship", "kind": "code", "detail": "final"},
            ],
            "edges": [
                {"from": "gen", "to": "judge", "when": "always", "payload": "draft.txt"},
                {"from": "judge", "to": "ship", "when": "pass", "payload": "draft.txt"},
                {"from": "judge", "to": "gen", "when": "fail", "payload": "verdict.txt",
                 "loop": True},
            ],
            "open_questions": [],
        }

    def run_agent_flow(self, judge_body):
        pkg = self.build(self.agent_spec(), steps={
            "judge": judge_body, "ship": "echo shipped\n"})
        run_dir = self.dir / "run"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "brief.md").write_text("Build a widget.")
        stub = make_stub_claude(self.dir / "stub")
        code, out = run_workflow(pkg, run_dir, workdir=pkg, extra_path=stub)
        calls = (self.dir / "stub" / "calls.log").read_text().splitlines()
        prompts = (self.dir / "stub" / "prompts.log").read_text().split("---CALL---")
        return code, out, calls, prompts

    def test_model_and_tools_are_passed(self):
        _, _, calls, _ = self.run_agent_flow("exit 0\n")
        self.assertIn("--model sonnet", calls[0])
        self.assertIn("--allowed-tools Read Write", calls[0])

    def test_first_call_has_no_resume(self):
        _, _, calls, _ = self.run_agent_flow("exit 0\n")
        self.assertNotIn("--resume", calls[0])

    def test_retry_resumes_the_prior_session(self):
        """A producer that just failed holds the context of what it attempted; it only
        lacks the news that it failed. Starting cold throws away the former."""
        counter = 'n=$(cat "$PWD/jc" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "$PWD/jc"\n'
        _, _, calls, _ = self.run_agent_flow(
            counter + '[ "$n" -ge 2 ] && exit 0; echo "REJECTED: too thin"; exit 1\n')
        self.assertGreaterEqual(len(calls), 2, calls)
        self.assertIn("--resume sess-1", calls[1])

    def test_payloads_and_feedback_substitute_into_the_prompt(self):
        counter = 'n=$(cat "$PWD/jc" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "$PWD/jc"\n'
        _, _, _, prompts = self.run_agent_flow(
            counter + '[ "$n" -ge 2 ] && exit 0; echo "REJECTED: too thin"; exit 1\n')
        self.assertIn("Build a widget.", prompts[0])
        self.assertIn("REJECTED: too thin", prompts[1])

    def test_authoring_notes_never_reach_the_model(self):
        _, _, _, prompts = self.run_agent_flow("exit 0\n")
        self.assertNotIn("<!--", prompts[0])
        self.assertNotIn("TODO: state exactly", prompts[0].split("What to produce")[0])


class TestOperatorAffordances(ScaffoldCase):
    def test_only_runs_a_single_node(self):
        """Payloads are files precisely so one node can be rerun against a fixed input."""
        pkg = self.build(loop_spec(), steps={
            "work": "echo isolated\n", "check": "exit 0\n", "ship": "echo shipped\n"})
        code, out = run_workflow(pkg, self.dir / "run", workdir=pkg, args=("--only", "work"))
        self.assertEqual(code, 0, out)
        self.assertIn("isolated", out)
        self.assertNotIn("ship", out)

    def test_unknown_node_is_rejected(self):
        pkg = self.build(loop_spec(), steps={"work": "exit 0\n", "check": "exit 0\n",
                                             "ship": "exit 0\n"})
        code, out = run_workflow(pkg, self.dir / "run", workdir=pkg,
                                 args=("--only", "nope"))
        self.assertEqual(code, 2)
        self.assertIn("unknown node", out)

    def test_human_node_parks_instead_of_self_approving(self):
        """Unattended, a run that approves its own work removes the only check that
        node existed to provide. 75 is EX_TEMPFAIL: waiting on a person, not broken."""
        pkg = self.build(valid_spec(), steps={"check": "exit 0\n"})
        stub = make_stub_claude(self.dir / "stub")
        code, out = run_workflow(pkg, self.dir / "run", workdir=pkg, extra_path=stub)
        self.assertEqual(code, 75, out)
        self.assertIn("stops here rather than deciding for you", out)


if __name__ == "__main__":
    unittest.main()
