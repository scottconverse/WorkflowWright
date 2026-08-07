"""Rendering: Mermaid generation, the three outputs, and the artifact's self-containment.

Several of these lock in regressions found during development rather than hypothetical
failures — see the comments on each.
"""

import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from helpers import EXAMPLE_SPEC, SCRIPTS, tmpdir, valid_spec, write_spec

import render_workflow as rw


class TestMermaidGeneration(unittest.TestCase):
    def setUp(self):
        self.mm = rw.build_mermaid(valid_spec())

    def test_shape_encodes_who_does_the_work(self):
        """Shape is the diagram's primary signal: code is square, agents round, humans hex."""
        self.assertIn('check["Check it"]', self.mm)
        self.assertIn('make("Make it', self.mm)
        self.assertIn('ship{{"Ship it"}}', self.mm)

    def test_kind_classes_applied(self):
        self.assertIn("class check code;", self.mm)
        self.assertIn("class make agent;", self.mm)
        self.assertIn("class ship human;", self.mm)

    def test_loop_edges_are_dashed_and_labelled(self):
        self.assertIn('check -. "fail: report.txt" .-> make', self.mm)

    def test_forward_edges_are_solid(self):
        self.assertIn('make -- "artifact" --> check', self.mm)

    def test_model_and_retry_annotated_on_node(self):
        self.assertIn("sonnet", self.mm)
        self.assertIn("max 3 attempts", self.mm)

    def test_no_small_tags_in_labels(self):
        """Regression: htmlLabels is off so labels render as SVG text, which measures
        correctly headlessly but renders <small> literally. Only <br/> survives."""
        self.assertNotIn("<small>", self.mm)
        self.assertIn("<br/>", self.mm)


class TestDefensiveRendering(unittest.TestCase):
    """Regression: an invalid spec used to raise instead of reporting.

    A design tool should show you the problem in context, not a traceback.
    """

    def test_unknown_kind_does_not_raise(self):
        spec = valid_spec()
        spec["nodes"][1]["kind"] = "robot"
        self.assertIn("check", rw.build_mermaid(spec))

    def test_dangling_edge_is_skipped_not_fatal(self):
        spec = valid_spec()
        spec["edges"][0]["to"] = "ghost"
        mm = rw.build_mermaid(spec)
        self.assertNotIn("ghost", mm)
        self.assertIn("make", mm)


class TestOutputs(unittest.TestCase):
    def setUp(self):
        self.out = Path(tmpdir())

    def tearDown(self):
        shutil.rmtree(self.out, ignore_errors=True)

    def render(self, spec_path, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPTS / "render_workflow.py"), str(spec_path),
             "--out", str(self.out), *args],
            capture_output=True, text=True,
        )

    def test_produces_all_three_outputs(self):
        proc = self.render(EXAMPLE_SPEC, "--no-prerender")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for name in ("ticket-to-pr-design.md", "ticket-to-pr.mermaid", "ticket-to-pr.html"):
            self.assertTrue((self.out / name).exists(), f"missing {name}")

    def test_design_doc_covers_the_decisions(self):
        self.render(EXAMPLE_SPEC, "--no-prerender")
        doc = (self.out / "ticket-to-pr-design.md").read_text()
        for section in ("## Nodes", "## Flow", "## Where people are involved",
                        "## Model and tool allocation", "## Open questions"):
            self.assertIn(section, doc)

    def test_invalid_spec_exits_nonzero_but_still_renders(self):
        """A work-in-progress design should render with its holes visible."""
        spec = valid_spec()
        spec["nodes"][0].pop("max_attempts")
        proc = self.render(write_spec(self.out, spec), "--no-prerender")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("max_attempts", proc.stderr)
        html = (self.out / "fixture.html").read_text()
        self.assertIn("Structural problems", html)

    def test_fallback_uses_cdn(self):
        self.render(EXAMPLE_SPEC, "--no-prerender")
        html = (self.out / "ticket-to-pr.html").read_text()
        self.assertIn("cdnjs.cloudflare.com", html)

    def test_html_escapes_injected_content(self):
        spec = valid_spec()
        spec["goal"] = 'Break <script>alert("x")</script> out'
        self.render(write_spec(self.out, spec), "--no-prerender")
        html = (self.out / "fixture.html").read_text()
        self.assertNotIn("<script>alert", html)
        self.assertIn("&lt;script&gt;", html)


@unittest.skipUnless(
    __import__("importlib").util.find_spec("playwright"),
    "playwright not installed; pre-rendering falls back to CDN",
)
class TestPreRendering(unittest.TestCase):
    """Regression: a CDN-loaded diagram renders an empty box in a sandboxed viewer,
    which is exactly where a persisted artifact lives."""

    def setUp(self):
        self.out = Path(tmpdir())

    def tearDown(self):
        shutil.rmtree(self.out, ignore_errors=True)

    def test_artifact_is_self_contained(self):
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / "render_workflow.py"), str(EXAMPLE_SPEC),
             "--out", str(self.out)],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        html = (self.out / "ticket-to-pr.html").read_text()
        if "could not pre-render" in proc.stderr:
            self.skipTest("no browser or network available for pre-rendering")
        self.assertIn("<svg", html)
        self.assertNotIn("cdnjs.cloudflare.com", html)


if __name__ == "__main__":
    unittest.main()
