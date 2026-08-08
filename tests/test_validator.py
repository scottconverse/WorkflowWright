"""The validator is the skill's opinion expressed as code.

Each test below corresponds to a structural failure that is cheap to fix in a spec and
expensive to fix once it is generated code or a running workflow.
"""

import unittest

from helpers import valid_spec

import render_workflow as rw


def problems_for(mutate):
    spec = valid_spec()
    mutate(spec)
    return rw.validate(spec)


def has(problems, *fragments):
    joined = " ".join(problems).lower()
    return all(f.lower() in joined for f in fragments)


class TestAcceptsValidSpecs(unittest.TestCase):
    def test_fixture_is_clean(self):
        self.assertEqual(rw.validate(valid_spec()), [])

    def test_bundled_example_is_clean(self):
        from helpers import EXAMPLE_SPEC

        self.assertEqual(rw.validate(rw.load_spec(EXAMPLE_SPEC)), [])


class TestRetryBounds(unittest.TestCase):
    """Unbounded retries against a paid API are the costliest error the validator catches."""

    def test_retry_target_without_max_attempts(self):
        p = problems_for(lambda s: s["nodes"][0].pop("max_attempts"))
        self.assertTrue(has(p, "max_attempts"), p)

    def test_retry_target_without_on_exhausted(self):
        p = problems_for(lambda s: s["nodes"][0].pop("on_exhausted"))
        self.assertTrue(has(p, "on_exhausted"), p)

    def test_zero_max_attempts_rejected(self):
        p = problems_for(lambda s: s["nodes"][0].update(max_attempts=0))
        self.assertTrue(has(p, "max_attempts"), p)

    def test_node_not_targeted_by_failure_needs_no_bound(self):
        """A checker fails routinely by design; it is not itself being retried."""
        spec = valid_spec()
        self.assertNotIn("max_attempts", spec["nodes"][1])
        self.assertEqual(rw.validate(spec), [])


class TestFailurePaths(unittest.TestCase):
    def test_pass_edge_without_fail_edge(self):
        p = problems_for(lambda s: s["edges"].__setitem__(2, dict(s["edges"][2], when="pass")))
        self.assertTrue(has(p, "fail"), p)

    def test_fail_edge_without_pass_edge(self):
        def mutate(s):
            s["edges"] = [e for e in s["edges"] if e["when"] != "pass"]

        p = problems_for(mutate)
        self.assertTrue(has(p, "success path"), p)

    def test_every_path_looping_forever(self):
        def mutate(s):
            s["edges"] = [e for e in s["edges"] if e["to"] != "ship"]
            s["nodes"] = [n for n in s["nodes"] if n["id"] != "ship"]

        p = problems_for(mutate)
        self.assertTrue(has(p, "terminal"), p)


class TestReferentialIntegrity(unittest.TestCase):
    def test_entry_not_a_node(self):
        p = problems_for(lambda s: s.update(entry="ghost"))
        self.assertTrue(has(p, "entry", "ghost"), p)

    def test_dangling_edge_target(self):
        p = problems_for(lambda s: s["edges"][0].update(to="ghost"))
        self.assertTrue(has(p, "ghost"), p)

    def test_duplicate_node_ids(self):
        p = problems_for(lambda s: s["nodes"].append(dict(s["nodes"][0])))
        self.assertTrue(has(p, "duplicate"), p)


class TestResourceAssignment(unittest.TestCase):
    def test_unknown_kind(self):
        p = problems_for(lambda s: s["nodes"][1].update(kind="robot"))
        self.assertTrue(has(p, "robot"), p)

    def test_model_on_a_code_node(self):
        """Only agent nodes run a model; a model on code is a category error."""
        p = problems_for(lambda s: s["nodes"][1].update(model="opus"))
        self.assertTrue(has(p, "only agent nodes"), p)

    def test_bad_edge_condition(self):
        p = problems_for(lambda s: s["edges"][0].update(when="maybe"))
        self.assertTrue(has(p, "must be always"), p)


class TestNamedPayloads(unittest.TestCase):
    def test_unnamed_edge_is_flagged(self):
        """An edge with no payload carries an assumption rather than data."""
        p = problems_for(lambda s: s["edges"][0].pop("payload"))
        self.assertTrue(has(p, "payload"), p)


class TestEvidenceDeclarations(unittest.TestCase):
    def test_evidence_without_a_failure_path_is_structural(self):
        """Evidence turns a missing artifact into a node failure. A node with
        nowhere to route a failure would simply stop the run there, which is
        the defect this validator already refuses in every other form."""
        spec = valid_spec()
        # `make` reaches `check` by an `always` edge and has no fail edge.
        for node in spec["nodes"]:
            if node["id"] == "make":
                node["evidence"] = "draft.md"
        problems = rw.validate(spec)
        self.assertTrue(any("evidence" in p and "make" in p for p in problems), problems)

    def test_evidence_with_a_failure_path_is_fine(self):
        spec = valid_spec()
        for node in spec["nodes"]:
            if node["id"] == "check":
                node["evidence"] = "report.txt"
        self.assertEqual(rw.validate(spec), [])

    def test_evidence_must_name_an_artifact(self):
        spec = valid_spec()
        for node in spec["nodes"]:
            if node["id"] == "check":
                node["evidence"] = ["a", "b"]
        self.assertTrue(any("evidence" in p for p in rw.validate(spec)))


class TestBudgetField(unittest.TestCase):
    def test_budget_must_be_a_positive_whole_number(self):
        spec = valid_spec()
        spec["budget"] = {"agent_calls": 0}
        self.assertTrue(any("agent_calls" in p for p in rw.validate(spec)))

    def test_a_real_budget_validates(self):
        spec = valid_spec()
        spec["budget"] = {"agent_calls": 5}
        self.assertEqual(rw.validate(spec), [])

    def test_budget_must_be_an_object(self):
        spec = valid_spec()
        spec["budget"] = 20
        self.assertTrue(any("budget" in p for p in rw.validate(spec)))


if __name__ == "__main__":
    unittest.main()
