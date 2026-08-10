#!/usr/bin/env python3
"""Install the skill into a directory, replacing whatever version was there.

    python3 scripts/install.py [DIR]        # default: ~/.claude/skills/workflowwright
    python3 scripts/install.py --dry-run    # say what would change, change nothing

This exists because `cp -r skill/. DIR/` -- what the Makefile used to run -- is a
*merge*, not a replace. It overwrites the files it has and silently leaves behind
the ones it does not. Nothing had been deleted between releases yet, so the bug
was invisible; the first renamed reference file would have left the old copy in
place beside the new one, with SKILL.md pointing at the new name and the stale
file still sitting there for something to read.

So this mirrors instead: after it runs, the target contains exactly what `skill/`
contains. That means deleting, which is why it carries the same two refusals as
uninstall.py -- a directory with no SKILL.md is not this skill and might be
anything, and a version-controlled working copy is somebody's checkout.

Every message here is ASCII on purpose. These print to a console whose encoding
is not ours to choose: cmd.exe defaults to cp437, and stdout raises rather than
substituting, so one decorative character replaces the report with a traceback.
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SOURCE = REPO / "skill"
DEFAULT = Path.home() / ".claude" / "skills" / "workflowwright"

# Same set uninstall.py refuses on, for the same reason.
VCS_MARKERS = (".git", ".hg", ".svn")

SKIP_DIRS = {"__pycache__"}
SKIP_SUFFIXES = {".pyc"}


def wanted(root: Path) -> set[str]:
    """Every file the skill consists of, as posix-relative paths."""
    return {
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file()
        and not SKIP_DIRS.intersection(p.parts)
        and p.suffix not in SKIP_SUFFIXES
    }


def refuse(target: Path) -> str:
    """Why this directory must not be written to, or '' if it is fine."""
    if not target.exists():
        return ""
    if not (target / "SKILL.md").is_file():
        return (f"no SKILL.md in {target}, so this is not a skill install. "
                "Refusing rather than overwriting something else.")
    marker = next((m for m in VCS_MARKERS if (target / m).exists()), None)
    if marker:
        return (f"{target} is a version-controlled working copy ({marker}/ is "
                "present). Installing would delete files git is tracking.")
    return ""


def install(target: Path, dry_run: bool = False) -> int:
    reason = refuse(target)
    if reason:
        print(f"refusing: {reason}")
        print("nothing was changed.")
        return 1

    source_files = wanted(SOURCE)
    existing = wanted(target) if target.exists() else set()

    added = sorted(source_files - existing)
    removed = sorted(existing - source_files)
    changed = sorted(
        rel for rel in source_files & existing
        if not filecmp.cmp(SOURCE / rel, target / rel, shallow=False)
    )

    for rel in removed:
        print(f"  remove  {rel}")
    for rel in added:
        print(f"  add     {rel}")
    for rel in changed:
        print(f"  update  {rel}")
    if not (added or removed or changed):
        print(f"already up to date -> {target}")
        return 0

    if dry_run:
        print(f"dry run: {len(added)} to add, {len(changed)} to update, "
              f"{len(removed)} to remove. Nothing was changed.")
        return 0

    for rel in removed:
        (target / rel).unlink()
    for rel in added + changed:
        destination = target / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SOURCE / rel, destination)

    # Directories left empty by a removal are part of the old version too.
    for directory in sorted((p for p in target.rglob("*") if p.is_dir()),
                            key=lambda p: len(p.parts), reverse=True):
        if not any(directory.iterdir()):
            directory.rmdir()

    print(f"installed -> {target}")
    print(f"  {len(added)} added, {len(changed)} updated, {len(removed)} removed")
    return 0


# The skill directory each host reads. They do not share, so a machine with more
# than one host has more than one copy, and copies drift -- which is the actual
# failure this addresses: two of three sat a version behind for a day because
# updating them was three commands nobody remembers to run.
HOSTS = {
    "Claude Code": Path.home() / ".claude" / "skills" / "workflowwright",
    "Codex": Path.home() / ".codex" / "skills" / "workflowwright",
    "Antigravity": Path.home() / ".gemini" / "config" / "skills" / "workflowwright",
}


def install_everywhere(dry_run: bool = False) -> int:
    """Update every host copy that already exists, and create none.

    Deliberately does not install where the skill is absent. A host you do not
    use should not gain a copy because you ran an update, and on Claude in
    particular a local install SHADOWS the account copy -- so creating one here
    would silently take over from the version that syncs between your machines.
    """
    present = {name: path for name, path in HOSTS.items() if path.exists()}
    if not present:
        print("no host copies found. Install one first, e.g.:")
        for name, path in HOSTS.items():
            print(f"  python3 scripts/install.py {path}    # {name}")
        return 0

    worst = 0
    for name, path in present.items():
        print(f"{name}: {path}")
        worst = max(worst, install(path, dry_run=dry_run))
        print("")

    skipped = [n for n in HOSTS if n not in present]
    if skipped:
        print(f"not installed, so not touched: {', '.join(skipped)}")
    print("the claude.ai account copy is an upload, not a directory -- "
          "run `make package` and upload the archive.")
    return worst


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("target", nargs="?", default=str(DEFAULT),
                        help="directory to install into (default: %(default)s)")
    parser.add_argument("--all", action="store_true",
                        help="update every host copy that already exists on this "
                             "machine, and create none")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would change and change nothing")
    args = parser.parse_args(argv)
    if args.all:
        return install_everywhere(dry_run=args.dry_run)
    return install(Path(args.target), dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
