#!/usr/bin/env python3
"""Remove a local skill install, refusing anything that isn't safe to delete.

    python3 scripts/uninstall.py [DIR]      # default: ~/.claude/skills/workflowwright

This exists as a script rather than a `rm -rf` in the Makefile for two reasons.
The directory is a variable, so the recipe is only ever as safe as whatever the
variable holds -- and `make` is not present on every machine this repo is
developed on, which would leave the guard both unrunnable and untested exactly
where it is needed most.

Two refusals, both from real ways this goes wrong:

  no SKILL.md   the path is not a skill install, so a mistyped directory cannot
                take out something unrelated.

  .git present  the ordinary way to work on a skill is to clone it and point a
                harness at the clone, which means the install IS the working
                copy. It has a SKILL.md, so the first guard passes, and deleting
                it would take the repository history -- including unpushed
                commits -- along with the skill.

Every message here is deliberately ASCII. These print to a console whose
encoding is not ours to choose: cmd.exe defaults to cp437, which has no em
dash, so a decorative character raises UnicodeEncodeError partway through and
replaces the explanation with a traceback.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

DEFAULT = Path.home() / ".claude" / "skills" / "workflowwright"

# Any of these marks a working copy under version control. Checked as a group
# rather than just .git so a hg or svn checkout is not a silent exception.
VCS_MARKERS = (".git", ".hg", ".svn")


def uninstall(target: Path, dry_run: bool = False) -> int:
    """Return a process exit status: 0 removed or nothing to do, 1 refused."""
    if not target.exists():
        print(f"nothing to do: {target} does not exist")
        return 0

    if not (target / "SKILL.md").is_file():
        print(f"refusing: no SKILL.md in {target}, so this is not the skill.")
        print("nothing was deleted.")
        return 1

    marker = next((m for m in VCS_MARKERS if (target / m).exists()), None)
    if marker:
        print(f"refusing: {target}")
        print(f"is a version-controlled working copy ({marker}/ is present).")
        print("Removing it would delete the repository history along with the")
        print("skill, including any commits not yet pushed.")
        print("")
        print("Nothing was deleted. Remove it with git, or delete the directory")
        print("yourself once the history is pushed or unwanted.")
        return 1

    if dry_run:
        print(f"would remove -> {target}")
        return 0

    shutil.rmtree(target)
    print(f"removed -> {target}")
    print("note: this removes only the local copy. A plugin install is removed")
    print("      with /plugin uninstall, and an account skill in its own settings.")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("target", nargs="?", default=str(DEFAULT),
                        help="directory to remove (default: %(default)s)")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would happen and change nothing")
    args = parser.parse_args(argv)
    return uninstall(Path(args.target), dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
