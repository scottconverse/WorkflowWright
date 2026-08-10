"""Installing must replace the previous version, not merge into it.

`make install` was `cp -r skill/. $(SKILL_DIR)/`, which overwrites the files it
has and leaves behind any the new version dropped. Nothing had been deleted
between releases yet, so it looked fine -- but the first renamed reference file
would have left the old copy sitting beside the new one, with SKILL.md naming
the new one and nothing to say the stale file was not still authoritative.

Because replacing means deleting, the installer carries the same two refusals as
the uninstaller, and those are checked here too.
"""

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from helpers import REPO, tmpdir


def run_install(target, *extra):
    return subprocess.run(
        [sys.executable, str(REPO / "scripts" / "install.py"), str(target), *extra],
        capture_output=True, text=True, timeout=120,
    )


class Installing(unittest.TestCase):
    def setUp(self):
        self.root = Path(tmpdir())
        self.addCleanup(shutil.rmtree, self.root, True)
        self.target = self.root / "workflowwright"

    def installed_files(self):
        return {p.relative_to(self.target).as_posix()
                for p in self.target.rglob("*") if p.is_file()}

    def test_installs_into_an_empty_directory(self):
        proc = run_install(self.target)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue((self.target / "SKILL.md").is_file())
        source = {p.relative_to(REPO / "skill").as_posix()
                  for p in (REPO / "skill").rglob("*")
                  if p.is_file() and "__pycache__" not in p.parts
                  and p.suffix != ".pyc"}
        self.assertEqual(self.installed_files(), source)

    def test_a_file_the_new_version_dropped_does_not_survive(self):
        """The whole reason this is a script and not a copy."""
        run_install(self.target)
        stale = self.target / "references" / "retired-guide.md"
        stale.write_text("removed in a later release\n", encoding="utf-8")

        proc = run_install(self.target)

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertFalse(stale.exists(),
                         "a file from the previous version survived the upgrade")
        self.assertIn("remove", proc.stdout)

    def test_an_emptied_directory_is_removed_too(self):
        run_install(self.target)
        orphan = self.target / "retired" / "old.md"
        orphan.parent.mkdir(parents=True, exist_ok=True)
        orphan.write_text("x\n", encoding="utf-8")

        run_install(self.target)

        self.assertFalse(orphan.parent.exists(),
                         "a directory left empty by the upgrade was kept")

    def test_reinstalling_the_same_version_changes_nothing(self):
        run_install(self.target)
        before = {p: p.stat().st_mtime_ns for p in self.target.rglob("*") if p.is_file()}

        proc = run_install(self.target)

        self.assertIn("already up to date", proc.stdout)
        after = {p: p.stat().st_mtime_ns for p in self.target.rglob("*") if p.is_file()}
        self.assertEqual(before, after, "an up-to-date install rewrote files")

    def test_dry_run_reports_and_changes_nothing(self):
        run_install(self.target)
        stale = self.target / "references" / "retired-guide.md"
        stale.write_text("removed in a later release\n", encoding="utf-8")

        proc = run_install(self.target, "--dry-run")

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("dry run", proc.stdout)
        self.assertTrue(stale.exists(), "--dry-run deleted something")

    def test_the_installed_version_is_the_current_one(self):
        run_install(self.target)
        installed = json.loads(
            (self.target / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        source = json.loads(
            (REPO / "skill" / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(installed["version"], source["version"])


class UpdateEverywhere(unittest.TestCase):
    """`--all` updates the copies that exist and creates none.

    Two of three host copies on the author's machine sat a version behind for a
    day, because keeping them level was three separate commands. Creating
    missing ones would be worse than leaving them: on Claude a local install
    shadows the account copy, so an update that helpfully created one would
    silently take over from the version that syncs between machines.
    """

    def setUp(self):
        self.root = Path(tmpdir())
        self.addCleanup(shutil.rmtree, self.root, True)
        sys.path.insert(0, str(REPO / "scripts"))
        import install as installer  # noqa: E402
        self.installer = installer
        self.addCleanup(sys.path.remove, str(REPO / "scripts"))
        self.original = installer.HOSTS.copy()
        self.addCleanup(setattr, installer, "HOSTS", self.original)

    def test_updates_only_the_copies_that_already_exist(self):
        present = self.root / "present"
        absent = self.root / "absent"
        run_install(present)
        self.installer.HOSTS = {"Present": present, "Absent": absent}

        stale = present / "references" / "gone.md"
        stale.write_text("old\n", encoding="utf-8")

        code = self.installer.install_everywhere()

        self.assertEqual(code, 0)
        self.assertFalse(stale.exists(), "the existing copy was not updated")
        self.assertFalse(absent.exists(), "--all created a copy that was not there")

    def test_says_so_when_nothing_is_installed(self):
        self.installer.HOSTS = {"Absent": self.root / "nope"}
        code = self.installer.install_everywhere()
        self.assertEqual(code, 0)
        self.assertFalse((self.root / "nope").exists())


class Refusals(unittest.TestCase):
    """Same two as the uninstaller, for the same reason: this deletes."""

    def setUp(self):
        self.root = Path(tmpdir())
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_refuses_a_directory_that_is_not_a_skill(self):
        target = self.root / "someone-elses-work"
        target.mkdir()
        (target / "important.txt").write_text("do not delete me\n", encoding="utf-8")

        proc = run_install(target)

        self.assertEqual(proc.returncode, 1)
        self.assertIn("no SKILL.md", proc.stdout)
        self.assertTrue((target / "important.txt").exists())

    def test_refuses_a_version_controlled_working_copy(self):
        target = self.root / "workflowwright"
        run_install(target)
        (target / ".git").mkdir()

        proc = run_install(target)

        self.assertEqual(proc.returncode, 1)
        self.assertIn("version-controlled", proc.stdout)


if __name__ == "__main__":
    unittest.main()
