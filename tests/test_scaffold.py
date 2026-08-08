"""Scaffolding and the generated driver's runtime behaviour.

The driver tests matter most: retry accounting and session resume are the two things
that are easy to get subtly wrong by hand, and both were wrong in an early version of
this generator. They are exercised here against a stub CLI, so no credentials, network,
or token spend is involved.
"""

import json
import os
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
            (pkg / "steps" / f"{node_id}.sh").write_text(body, encoding="utf-8")
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
        pkg = self.build(EXAMPLE_SPEC and json.loads(Path(EXAMPLE_SPEC).read_text(encoding="utf-8")))
        proc = subprocess.run(
            [sys.executable, "-c",
             f"import sys; sys.path.insert(0, {str(pkg)!r}); import workflow; "
             "print(len(workflow.NODES), sorted(workflow.RETRY_TARGETS))"],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("7 ['build']", proc.stdout)

    def test_generated_files_are_utf8(self):
        """Regression: an unqualified write_text() emits the platform codepage, which
        on Windows is cp1252. The em dashes in the generated docstrings then make
        workflow.py unreadable as Python source, since PEP 263 assumes UTF-8."""
        pkg = self.build(valid_spec())
        raw = (pkg / "workflow.py").read_bytes()
        self.assertTrue(
            any(b > 0x7F for b in raw),
            "workflow.py has no non-ASCII bytes left to pin the encoding against",
        )
        raw.decode("utf-8")
        for name in ("runner.py", "README.md", "prompts/make.md", "steps/check.sh"):
            (pkg / name).read_bytes().decode("utf-8")

    @unittest.skipUnless(os.name == "nt", "exercises Windows bash resolution")
    def test_missing_bash_fails_loudly_naming_workflow_bash(self):
        """With no usable bash, the runner must stop and name WORKFLOW_BASH.
        An unqualified "bash" fallback would hand step scripts to System32's
        WSL launcher — which mangles Windows paths — silently."""
        import importlib.util

        pkg = self.build(valid_spec())
        loader_spec = importlib.util.spec_from_file_location(
            "runner_probe", pkg / "runner.py"
        )
        mod = importlib.util.module_from_spec(loader_spec)
        sys.modules["runner_probe"] = mod
        self.addCleanup(sys.modules.pop, "runner_probe", None)
        loader_spec.loader.exec_module(mod)
        # An empty environ: no override, no Git detection, no PATH. Passed
        # explicitly because stripping a real child's environment is unreliable
        # (case-insensitive keys, and sandboxes that re-inject variables).
        with self.assertRaises(SystemExit) as ctx:
            mod._bash({})
        self.assertIn("WORKFLOW_BASH", str(ctx.exception))

    def test_regeneration_preserves_hand_written_work(self):
        spec = valid_spec()
        pkg = self.build(spec)
        (pkg / "prompts" / "make.md").write_text("MY PROMPT", encoding="utf-8")
        (pkg / "steps" / "check.sh").write_text("MY STEP", encoding="utf-8")
        proc = scaffold(write_spec(self.dir, spec), pkg)
        self.assertIn("kept", proc.stdout)
        self.assertEqual((pkg / "prompts" / "make.md").read_text(encoding="utf-8"), "MY PROMPT")
        self.assertEqual((pkg / "steps" / "check.sh").read_text(encoding="utf-8"), "MY STEP")

    def test_force_overwrites(self):
        spec = valid_spec()
        pkg = self.build(spec)
        (pkg / "prompts" / "make.md").write_text("MY PROMPT", encoding="utf-8")
        scaffold(write_spec(self.dir, spec), pkg, "--force")
        self.assertNotEqual((pkg / "prompts" / "make.md").read_text(encoding="utf-8"), "MY PROMPT")

    def test_steps_start_as_honest_failures(self):
        """A stub that exits 0 would let an empty workflow report success."""
        pkg = self.build(valid_spec())
        self.assertIn("exit 1", (pkg / "steps" / "check.sh").read_text(encoding="utf-8"))


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
        self.assertIn("shipped", (self.dir / "run" / "ship.out").read_text(encoding="utf-8"))

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
                      (self.dir / "run" / "report.txt").read_text(encoding="utf-8"))


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
        (run_dir / "brief.md").write_text("Build a widget.", encoding="utf-8")
        stub = make_stub_claude(self.dir / "stub")
        code, out = run_workflow(pkg, run_dir, workdir=pkg, agent_cli=stub)
        calls = (self.dir / "stub" / "calls.log").read_text(encoding="utf-8").splitlines()
        prompts = (self.dir / "stub" / "prompts.log").read_text(encoding="utf-8").split("---CALL---")
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

    def test_large_prompt_survives_the_process_boundary(self):
        """Prompts travel on stdin because argv has hard ceilings — 32767 chars
        under CreateProcess, 8191 through cmd.exe shims (which also truncate at
        the first newline). A payload-bearing prompt exceeds those routinely."""
        payload = (
            'a line with "double quotes", \'single quotes\', a back\\slash,\n'
            "an em dash — and a newline\n"
        ) * 200  # ≈ 17KB, comfortably past both argv ceilings
        pkg = self.build(self.agent_spec(), steps={
            "judge": "exit 0\n", "ship": "echo shipped\n"})
        run_dir = self.dir / "run"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "brief.md").write_text(payload, encoding="utf-8")
        stub = make_stub_claude(self.dir / "stub")
        code, out = run_workflow(pkg, run_dir, workdir=pkg, agent_cli=stub)
        self.assertEqual(code, 0, out)
        prompts = (self.dir / "stub" / "prompts.log").read_text(encoding="utf-8")
        self.assertGreater(len(payload), 10_000)
        self.assertIn(payload.strip(), prompts)

    def test_authoring_notes_never_reach_the_model(self):
        _, _, _, prompts = self.run_agent_flow("exit 0\n")
        self.assertNotIn("<!--", prompts[0])
        self.assertNotIn("TODO: state exactly", prompts[0].split("What to produce")[0])


class TestDelegateMode(ScaffoldCase):
    """Agent nodes done by whoever is driving, instead of by a CLI subprocess.

    The mode exists for people working inside an assistant rather than a
    terminal: no CLI on PATH, no nested session spending tokens out of sight.
    The deterministic half must behave identically, which is what these check.
    """

    def agent_spec(self):
        return TestAgentInvocation.agent_spec(self)

    def test_parks_at_the_first_agent_node_and_writes_the_prompt(self):
        pkg = self.build(self.agent_spec(), steps={
            "judge": "exit 0\n", "ship": "echo shipped\n"})
        run_dir = self.dir / "run"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "brief.md").write_text("Build a widget.", encoding="utf-8")
        code, out = run_workflow(pkg, run_dir, workdir=pkg, delegate=True)
        self.assertEqual(code, 76, out)
        prompt = (run_dir / "gen.prompt.md").read_text(encoding="utf-8")
        # The parked prompt is the fully composed one, payloads substituted —
        # the operator must see exactly what a model would have received.
        self.assertIn("Build a widget.", prompt)
        self.assertNotIn("<!--", prompt)
        self.assertIn("gen.result.md", out)

    def test_answer_is_consumed_and_the_run_continues(self):
        pkg = self.build(self.agent_spec(), steps={
            "judge": "exit 0\n", "ship": "echo shipped\n"})
        run_dir = self.dir / "run"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "brief.md").write_text("Build a widget.", encoding="utf-8")
        self.assertEqual(run_workflow(pkg, run_dir, workdir=pkg, delegate=True)[0], 76)

        (run_dir / "gen.result.md").write_text("the draft", encoding="utf-8")
        code, out = run_workflow(pkg, run_dir, workdir=pkg, delegate=True)
        self.assertEqual(code, 0, out)
        self.assertIn("shipped", (run_dir / "ship.out").read_text(encoding="utf-8"))
        # Consumed rather than deleted: still readable, but cannot be mistaken
        # for the answer to a later attempt.
        self.assertFalse((run_dir / "gen.result.md").exists())
        self.assertTrue((run_dir / "gen.result.consumed.md").exists())

    def test_retry_ceiling_survives_repeated_parking(self):
        """The regression this mode could most easily introduce.

        Each pause kills the process. If attempts were not persisted, every
        resume would restart the count and the loop would never exhaust; if the
        resumed attempt were counted twice, a ceiling of three would be hit in
        two. Neither is acceptable for the thing that stops runaway spend."""
        pkg = self.build(self.agent_spec(), steps={
            "judge": 'echo "REJECTED: too thin"; exit 1\n', "ship": "echo shipped\n"})
        run_dir = self.dir / "run"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "brief.md").write_text("Build a widget.", encoding="utf-8")

        parks = 0
        for _ in range(10):
            code, out = run_workflow(pkg, run_dir, workdir=pkg, delegate=True)
            if code != 76:
                break
            parks += 1
            (run_dir / "gen.result.md").write_text(f"draft {parks}", encoding="utf-8")
        else:
            self.fail("delegated loop never terminated")

        # max_attempts is 3, so exactly three delegated attempts then failure.
        self.assertEqual(parks, 3, out)
        self.assertEqual(code, 1, out)
        self.assertIn("giving up after 3", out)

    def test_feedback_reaches_the_retried_prompt_across_a_pause(self):
        pkg = self.build(self.agent_spec(), steps={
            "judge": 'echo "REJECTED: too thin"; exit 1\n', "ship": "echo shipped\n"})
        run_dir = self.dir / "run"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "brief.md").write_text("Build a widget.", encoding="utf-8")

        run_workflow(pkg, run_dir, workdir=pkg, delegate=True)
        (run_dir / "gen.result.md").write_text("first draft", encoding="utf-8")
        run_workflow(pkg, run_dir, workdir=pkg, delegate=True)
        # Second park: the prompt must carry the checker's complaint, or the
        # operator redoes the work blind exactly as an amnesiac retry would.
        self.assertIn("REJECTED: too thin",
                      (run_dir / "gen.prompt.md").read_text(encoding="utf-8"))

    def test_empty_answer_is_a_failure_not_a_silent_pass(self):
        pkg = self.build(self.agent_spec(), steps={
            "judge": "exit 0\n", "ship": "echo shipped\n"})
        run_dir = self.dir / "run"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "brief.md").write_text("Build a widget.", encoding="utf-8")
        run_workflow(pkg, run_dir, workdir=pkg, delegate=True)
        (run_dir / "gen.result.md").write_text("   \n", encoding="utf-8")
        code, out = run_workflow(pkg, run_dir, workdir=pkg, delegate=True)
        self.assertNotEqual(code, 0, out)

    def test_state_is_cleared_so_a_finished_run_does_not_resume(self):
        pkg = self.build(self.agent_spec(), steps={
            "judge": "exit 0\n", "ship": "echo shipped\n"})
        run_dir = self.dir / "run"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "brief.md").write_text("Build a widget.", encoding="utf-8")
        run_workflow(pkg, run_dir, workdir=pkg, delegate=True)
        (run_dir / "gen.result.md").write_text("the draft", encoding="utf-8")
        run_workflow(pkg, run_dir, workdir=pkg, delegate=True)
        self.assertFalse((run_dir / "driver-state.json").exists())

    def test_default_mode_still_uses_the_cli(self):
        """Delegation is additive: without the switch nothing changes."""
        pkg = self.build(self.agent_spec(), steps={
            "judge": "exit 0\n", "ship": "echo shipped\n"})
        run_dir = self.dir / "run"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "brief.md").write_text("Build a widget.", encoding="utf-8")
        stub = make_stub_claude(self.dir / "stub")
        code, out = run_workflow(pkg, run_dir, workdir=pkg, agent_cli=stub)
        self.assertEqual(code, 0, out)
        self.assertFalse((run_dir / "gen.prompt.md").exists(),
                         "subprocess mode must not park or write a delegate prompt")
        self.assertTrue((self.dir / "stub" / "calls.log").exists())


class TestHumanGateDelegation(ScaffoldCase):
    """Human gates answerable without a terminal, and recorded when answered.

    An approval that only works at a TTY is unavailable to anyone driving a
    workflow from inside an assistant, which is where these workflows are most
    often run. Parking a human gate the way an agent node parks makes the
    decision possible at all — and makes recording it a byproduct rather than a
    separate mechanism.
    """

    def gate_spec(self):
        """Entry code node, then a human gate. Minimal, so failures are legible."""
        return {
            "name": "gate", "goal": "exercise a human gate", "trigger": "manual",
            "isolation": "none", "entry": "prep",
            "nodes": [
                {"id": "prep", "label": "Prepare", "kind": "code", "detail": "sets up"},
                {"id": "approve", "label": "Approve the change", "kind": "human",
                 "detail": "Decide whether this is safe to ship."},
                {"id": "ship", "label": "Ship", "kind": "code", "detail": "final"},
            ],
            "edges": [
                {"from": "prep", "to": "approve", "when": "always", "payload": "work.txt"},
                {"from": "approve", "to": "ship", "when": "pass", "payload": "work.txt"},
                {"from": "approve", "to": "prep", "when": "fail", "payload": "why.txt",
                 "loop": True},
            ],
            "open_questions": [],
        }

    def gate_pkg(self):
        pkg = self.build(self.gate_spec(), steps={
            "prep": "echo prepared\n", "ship": "echo shipped\n"})
        # prep is a retry target, so it needs a bound; add it to the spec instead
        # of hand-editing the generated package.
        return pkg

    def build_gate(self):
        spec = self.gate_spec()
        for node in spec["nodes"]:
            if node["id"] == "prep":
                node["max_attempts"] = 2
                node["on_exhausted"] = "fail"
        return self.build(spec, steps={"prep": "echo prepared\n", "ship": "echo shipped\n"})

    def test_gate_parks_and_names_the_answer_file(self):
        pkg = self.build_gate()
        run_dir = self.dir / "run"
        code, out = run_workflow(pkg, run_dir, workdir=pkg, delegate=True)
        self.assertEqual(code, 75, out)
        request = (run_dir / "approve.decision.md").read_text(encoding="utf-8")
        self.assertIn("Approve the change", request)
        self.assertIn("Decide whether this is safe to ship.", request)
        self.assertIn("approve.answer.md", out)

    def test_yes_approves_and_records_the_decision(self):
        pkg = self.build_gate()
        run_dir = self.dir / "run"
        run_workflow(pkg, run_dir, workdir=pkg, delegate=True)
        (run_dir / "approve.answer.md").write_text(
            "yes\nChecked the migration against staging.", encoding="utf-8")
        code, out = run_workflow(pkg, run_dir, workdir=pkg, delegate=True)
        self.assertEqual(code, 0, out)
        record = json.loads((run_dir / "approve.decision.json").read_text(encoding="utf-8"))
        self.assertEqual(record["node"], "approve")
        self.assertTrue(record["approved"])
        self.assertIn("staging", record["rationale"])
        self.assertTrue(record["at"], "a decision with no timestamp is not a record")

    def test_no_rejects_and_still_records(self):
        pkg = self.build_gate()
        run_dir = self.dir / "run"
        run_workflow(pkg, run_dir, workdir=pkg, delegate=True)
        (run_dir / "approve.answer.md").write_text(
            "no\nThe rollback path is untested.", encoding="utf-8")
        run_workflow(pkg, run_dir, workdir=pkg, delegate=True)
        record = json.loads((run_dir / "approve.decision.json").read_text(encoding="utf-8"))
        self.assertFalse(record["approved"])
        self.assertIn("rollback", record["rationale"])

    def test_an_unrecognised_answer_never_approves(self):
        """The safety property. Ambiguity must not read as consent — an answer
        the parser does not understand is the case where a human meant
        something, and guessing approval is the one wrong way to resolve it."""
        pkg = self.build_gate()
        run_dir = self.dir / "run"
        run_workflow(pkg, run_dir, workdir=pkg, delegate=True)
        (run_dir / "approve.answer.md").write_text(
            "well, maybe, if the tests look ok?", encoding="utf-8")
        run_workflow(pkg, run_dir, workdir=pkg, delegate=True)
        record = json.loads((run_dir / "approve.decision.json").read_text(encoding="utf-8"))
        self.assertFalse(record["approved"])

    def test_answer_is_consumed_so_a_later_gate_cannot_reuse_it(self):
        pkg = self.build_gate()
        run_dir = self.dir / "run"
        run_workflow(pkg, run_dir, workdir=pkg, delegate=True)
        (run_dir / "approve.answer.md").write_text("yes", encoding="utf-8")
        run_workflow(pkg, run_dir, workdir=pkg, delegate=True)
        self.assertFalse((run_dir / "approve.answer.md").exists())
        self.assertTrue((run_dir / "approve.answer.consumed.md").exists())

    def test_on_exhausted_human_parks_and_is_answerable(self):
        """The exhaustion handoff has to be answerable too, or a bounded loop
        that runs out simply dead-ends for anyone without a terminal."""
        spec = self.gate_spec()
        for node in spec["nodes"]:
            if node["id"] == "prep":
                node["max_attempts"] = 1
                node["on_exhausted"] = "human"
        pkg = self.build(spec, steps={"prep": "exit 1\n", "ship": "echo shipped\n"})
        run_dir = self.dir / "run"
        code, out = run_workflow(pkg, run_dir, workdir=pkg, delegate=True)
        self.assertEqual(code, 75, out)
        self.assertTrue((run_dir / "prep.decision.md").exists(),
                        "the exhaustion handoff must park like any other gate")

    def test_subprocess_mode_gate_is_unchanged(self):
        """Delegation is additive: without the switch, unattended still parks at
        75 with no answer file and no record."""
        pkg = self.build_gate()
        run_dir = self.dir / "run"
        code, out = run_workflow(pkg, run_dir, workdir=pkg)
        self.assertEqual(code, 75, out)
        self.assertIn("stops here rather than deciding for you", out)
        self.assertFalse((run_dir / "approve.decision.json").exists())


class TestRunBudget(ScaffoldCase):
    """A ceiling on agent calls for the whole run, not per node.

    max_attempts bounds each node independently, which leaves a real hole: two
    nodes on a loop edge can honour their own ceilings and still ping-pong,
    spending indefinitely. The budget closes it by counting across the run.
    """

    def budget_spec(self, agent_calls=None, max_attempts=5, gen_retries_itself=False):
        spec = {
            "name": "budgeted", "goal": "exercise the budget", "trigger": "manual",
            "isolation": "none", "entry": "gen",
            "nodes": [
                {"id": "gen", "label": "Generate", "kind": "agent", "detail": "make it",
                 "model": "sonnet", "reads": ["brief.md"], "writes": ["draft.txt"],
                 "max_attempts": max_attempts, "on_exhausted": "fail"},
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
        if gen_retries_itself:
            # gen's own failure loops back into gen, so a failing agent call is
            # retried rather than dead-ending: the shape needed to observe that
            # failed calls are charged.
            spec["edges"].append({"from": "gen", "to": "gen", "when": "fail",
                                  "payload": "error.txt", "loop": True})
        if agent_calls is not None:
            spec["budget"] = {"agent_calls": agent_calls}
        return spec

    def prep(self, spec, judge="exit 0\n"):
        pkg = self.build(spec, steps={"judge": judge, "ship": "echo shipped\n"})
        run_dir = self.dir / "run"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "brief.md").write_text("Build a widget.", encoding="utf-8")
        return pkg, run_dir

    def test_a_failing_call_still_spends_budget(self):
        """The refinement that matters. Counting only successful calls lets a
        crash-looping node spend real money while the counter stays flat, which
        is the exact runaway the budget exists to stop."""
        pkg, run_dir = self.prep(self.budget_spec(
            agent_calls=2, max_attempts=5, gen_retries_itself=True))
        stub = make_stub_claude(self.dir / "stub", fail_until=99)
        code, out = run_workflow(pkg, run_dir, workdir=pkg, agent_cli=stub)
        calls = (self.dir / "stub" / "calls.log").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(calls), 2, f"budget of 2 must stop after 2 launches\n{out}")
        self.assertNotEqual(code, 0, out)
        self.assertIn("budget", out.lower())

    def test_budget_stops_before_launching_the_call_that_would_exceed_it(self):
        pkg, run_dir = self.prep(
            self.budget_spec(agent_calls=1, max_attempts=5),
            judge='echo "REJECTED"; exit 1\n')
        stub = make_stub_claude(self.dir / "stub")
        code, out = run_workflow(pkg, run_dir, workdir=pkg, agent_cli=stub)
        calls = (self.dir / "stub" / "calls.log").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(calls), 1, out)
        self.assertEqual(code, 75, f"exhaustion is a handoff, not a crash\n{out}")

    def test_a_call_that_never_launched_is_free(self):
        """CLI missing means nothing ran and nothing was spent. If it counted,
        a bad PATH would drain the budget and report exhaustion instead of the
        precise cause, trading a real diagnosis for a misleading one."""
        pkg, run_dir = self.prep(self.budget_spec(agent_calls=2, max_attempts=3))
        code, out = run_workflow(pkg, run_dir, workdir=pkg,
                                 agent_cli="definitely-not-a-real-cli-xyz")
        self.assertIn("not on PATH", out)
        self.assertNotIn("budget", out.lower())

    def test_spend_survives_a_delegate_pause(self):
        """Every delegated pause is a fresh process. An in-memory counter would
        reset at each one, making any budget infinite in the mode most likely
        to be driven by a person watching the cost."""
        pkg, run_dir = self.prep(
            self.budget_spec(agent_calls=2, max_attempts=5),
            judge='echo "REJECTED"; exit 1\n')
        for i in range(2):
            code, out = run_workflow(pkg, run_dir, workdir=pkg, delegate=True)
            self.assertEqual(code, 76, out)
            (run_dir / "gen.result.md").write_text(f"draft {i}", encoding="utf-8")
        code, out = run_workflow(pkg, run_dir, workdir=pkg, delegate=True)
        self.assertEqual(code, 75, f"third attempt must hit the budget\n{out}")
        self.assertIn("budget", out.lower())

    def test_no_budget_field_means_no_ceiling(self):
        """Optional stays optional: a spec without the field behaves exactly as
        it did before the field existed."""
        pkg, run_dir = self.prep(
            self.budget_spec(agent_calls=None, max_attempts=3),
            judge='echo "REJECTED"; exit 1\n')
        stub = make_stub_claude(self.dir / "stub")
        code, out = run_workflow(pkg, run_dir, workdir=pkg, agent_cli=stub)
        calls = (self.dir / "stub" / "calls.log").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(calls), 3, "max_attempts alone should govern")
        self.assertNotIn("budget", out.lower())

    def test_exhaustion_records_the_decision(self):
        pkg, run_dir = self.prep(
            self.budget_spec(agent_calls=1, max_attempts=5),
            judge='echo "REJECTED"; exit 1\n')
        run_workflow(pkg, run_dir, workdir=pkg, delegate=True)
        (run_dir / "gen.result.md").write_text("draft", encoding="utf-8")
        run_workflow(pkg, run_dir, workdir=pkg, delegate=True)
        records = list(run_dir.glob("*.decision.md"))
        self.assertTrue(records, "a budget stop must hand off with context, not vanish")


class TestEvidenceGates(ScaffoldCase):
    """A node that claims success must leave something behind.

    The floor is deliberately low — the artifact exists and is not empty — and
    it is worth being precise about what that buys. It catches the silent
    no-op: the node that reported success and produced nothing. It does not
    catch a node that writes a token file to satisfy the check. That is a real
    limit, not a defect to paper over.
    """

    def ev_spec(self, evidence="report.txt", with_fail_edge=True):
        """work has BOTH an always edge and a fail edge, so the test can show
        that evidence gates the always traversal too, not only a pass edge."""
        spec = {
            "name": "evidenced", "goal": "exercise evidence", "trigger": "manual",
            "isolation": "none", "entry": "work",
            "nodes": [
                {"id": "work", "label": "Do the work", "kind": "code",
                 "detail": "produces a report", "max_attempts": 2,
                 "on_exhausted": "fail"},
                {"id": "ship", "label": "Ship", "kind": "code", "detail": "final"},
            ],
            "edges": [
                {"from": "work", "to": "ship", "when": "always", "payload": "report.txt"},
            ],
            "open_questions": [],
        }
        if evidence:
            spec["nodes"][0]["evidence"] = evidence
        if with_fail_edge:
            spec["edges"].append({"from": "work", "to": "work", "when": "fail",
                                  "payload": "shortfall.txt", "loop": True})
        return spec

    def test_evidence_present_lets_the_run_continue(self):
        pkg = self.build(self.ev_spec(), steps={
            "work": 'echo "the findings" > "$1/report.txt" 2>/dev/null || true\n'
                    'echo done\n',
            "ship": "echo shipped\n"})
        run_dir = self.dir / "run"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "report.txt").write_text("the findings", encoding="utf-8")
        code, out = run_workflow(pkg, run_dir, workdir=pkg)
        self.assertEqual(code, 0, out)
        self.assertIn("shipped", (run_dir / "ship.out").read_text(encoding="utf-8"))

    def test_missing_evidence_fails_a_node_that_reported_success(self):
        """The whole point: exit 0 is a claim, the artifact is the proof."""
        pkg = self.build(self.ev_spec(), steps={
            "work": "echo I did it\n", "ship": "echo shipped\n"})
        run_dir = self.dir / "run"
        code, out = run_workflow(pkg, run_dir, workdir=pkg)
        self.assertNotEqual(code, 0, out)
        self.assertIn("report.txt", out, "the message must name the missing artifact")
        self.assertFalse((run_dir / "ship.out").exists(),
                         "a node that proved nothing must not hand work downstream")

    def test_evidence_gates_the_always_edge_not_only_a_pass_edge(self):
        """work's success edge is `always`. Gating only `pass` edges would let
        it through untouched — and on the project's own example spec five of
        seven edges are `always`, so a pass-only gate would check almost
        nothing."""
        pkg = self.build(self.ev_spec(), steps={
            "work": "echo I did it\n", "ship": "echo shipped\n"})
        run_dir = self.dir / "run"
        code, out = run_workflow(pkg, run_dir, workdir=pkg)
        self.assertNotIn("shipped", out)
        self.assertIn("giving up after 2", out, "it should have retried, then stopped")

    def test_empty_evidence_counts_as_missing(self):
        pkg = self.build(self.ev_spec(), steps={
            "work": "echo I did it\n", "ship": "echo shipped\n"})
        run_dir = self.dir / "run"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "report.txt").write_text("   \n\n", encoding="utf-8")
        code, out = run_workflow(pkg, run_dir, workdir=pkg)
        self.assertNotEqual(code, 0, out)
        self.assertIn("empty", out.lower())

    def test_evidence_failure_consumes_an_attempt(self):
        """It is an ordinary failure, so it flows through the ordinary retry
        accounting rather than inventing a second kind of failure."""
        pkg = self.build(self.ev_spec(), steps={
            "work": "echo I did it\n", "ship": "echo shipped\n"})
        run_dir = self.dir / "run"
        code, out = run_workflow(pkg, run_dir, workdir=pkg)
        self.assertEqual(out.count("work [code]"), 2, f"max_attempts=2\n{out}")

    def test_an_already_failing_node_is_not_also_blamed_for_evidence(self):
        """Checked only on otherwise-successful outcomes: a node that already
        failed has a real reason, and replacing it with a missing-artifact
        complaint would bury the useful one."""
        pkg = self.build(self.ev_spec(), steps={
            "work": 'echo "the real reason"; exit 1\n', "ship": "echo shipped\n"})
        run_dir = self.dir / "run"
        code, out = run_workflow(pkg, run_dir, workdir=pkg)
        self.assertIn("the real reason", out)
        self.assertNotIn("declared evidence", out)

    def test_no_evidence_field_changes_nothing(self):
        pkg = self.build(self.ev_spec(evidence=None), steps={
            "work": "echo I did it\n", "ship": "echo shipped\n"})
        run_dir = self.dir / "run"
        code, out = run_workflow(pkg, run_dir, workdir=pkg)
        self.assertEqual(code, 0, out)
        self.assertIn("shipped", (run_dir / "ship.out").read_text(encoding="utf-8"))


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
        code, out = run_workflow(pkg, self.dir / "run", workdir=pkg, agent_cli=stub)
        self.assertEqual(code, 75, out)
        self.assertIn("stops here rather than deciding for you", out)


if __name__ == "__main__":
    unittest.main()
