"""The uninstaller must refuse anything that is not safely deletable.

Every case here is a way `rm -rf $(SKILL_DIR)` went wrong or would have. The
directory is a variable, so the operation is only as safe as what the variable
holds, and the two things it most plausibly holds by accident are somebody's
unrelated work and the clone the skill is being developed in.
"""

import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from helpers import REPO, tmpdir

sys.path.insert(0, str(REPO / "scripts"))
import uninstall as uninstaller  # noqa: E402


def make_install(root, *, skill_md=True, vcs=None):
    """A directory shaped like an install, optionally under version control."""
    target = Path(root) / "workflowwright"
    (target / "scripts").mkdir(parents=True)
    if skill_md:
        (target / "SKILL.md").write_text("---\nname: workflowwright\n---\n",
                                         encoding="utf-8")
    (target / "scripts" / "render_workflow.py").write_text("# stub\n",
                                                           encoding="utf-8")
    if vcs:
        (target / vcs).mkdir()
        (target / vcs / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    return target


class Refusals(unittest.TestCase):
    def setUp(self):
        self.root = tmpdir()
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_removes_a_plain_install(self):
        target = make_install(self.root)
        self.assertEqual(uninstaller.uninstall(target), 0)
        self.assertFalse(target.exists())

    def test_refuses_a_directory_that_is_not_a_skill(self):
        """A mistyped SKILL_DIR must not take out unrelated work."""
        target = make_install(self.root, skill_md=False)
        important = target / "scripts" / "render_workflow.py"

        self.assertEqual(uninstaller.uninstall(target), 1)
        self.assertTrue(important.is_file(), "refused, but deleted anyway")

    def test_refuses_a_git_working_copy(self):
        """The ordinary way to work on a skill is to point a harness at a clone.

        That install has a SKILL.md, so the first guard passes it through, and
        deleting it would take unpushed history along with the skill.
        """
        target = make_install(self.root, vcs=".git")

        self.assertEqual(uninstaller.uninstall(target), 1)
        self.assertTrue(target.exists())
        self.assertTrue((target / ".git" / "HEAD").is_file())

    def test_refuses_other_version_control_systems(self):
        for marker in (".hg", ".svn"):
            with self.subTest(marker=marker):
                root = tmpdir()
                self.addCleanup(shutil.rmtree, root, True)
                target = make_install(root, vcs=marker)

                self.assertEqual(uninstaller.uninstall(target), 1)
                self.assertTrue(target.exists())

    def test_a_missing_directory_is_not_an_error(self):
        """Uninstalling twice is a no-op, not a failure."""
        self.assertEqual(uninstaller.uninstall(Path(self.root) / "absent"), 0)

    def test_dry_run_changes_nothing(self):
        target = make_install(self.root)
        self.assertEqual(uninstaller.uninstall(target, dry_run=True), 0)
        self.assertTrue(target.exists())


class ConsoleEncoding(unittest.TestCase):
    """Output must survive a console encoding we do not get to choose.

    cmd.exe defaults to cp437, which has no em dash. A decorative character in a
    message raises UnicodeEncodeError partway through the run -- replacing the
    explanation of what was refused, and why, with a traceback.
    """

    def _run(self, *args):
        env = {**os.environ, "PYTHONIOENCODING": "cp437:strict"}
        return subprocess.run(
            [sys.executable, str(REPO / "scripts" / "uninstall.py"), *args],
            capture_output=True, text=True, env=env, timeout=60,
        )

    def test_refusal_message_encodes_on_a_cp437_console(self):
        root = tmpdir()
        self.addCleanup(shutil.rmtree, root, True)
        target = make_install(root, vcs=".git")

        proc = self._run(str(target))

        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertNotIn("UnicodeEncodeError", proc.stderr)
        self.assertIn("version-controlled", proc.stdout)

    def test_removal_message_encodes_on_a_cp437_console(self):
        root = tmpdir()
        self.addCleanup(shutil.rmtree, root, True)
        target = make_install(root)

        proc = self._run(str(target))

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("UnicodeEncodeError", proc.stderr)
        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
