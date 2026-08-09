#!/usr/bin/env python3
"""Build the archive you upload to a claude.ai account.

Usage:
    python3 scripts/build_package.py [--out build/workflowwright.zip]

SKILL.md goes at the archive root, not inside a wrapping folder. The uploader
rejects an archive whose SKILL.md is nested — including GitHub's own source zip,
where it lands at `WorkflowWright-main/skill/SKILL.md` — so the layout here is
the whole point of the script rather than an incidental detail.

Written in Python rather than shelling out to `zip` for the same reason the rest
of this project is stdlib-only: `zip` is absent on stock Windows, which is where
this archive most often gets built by someone who has no other reason to install
developer tooling.
"""

import argparse
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / "skill"
SKIP_DIRS = {"__pycache__"}
SKIP_SUFFIXES = {".pyc"}


def build(out: Path) -> list[str]:
    out.parent.mkdir(parents=True, exist_ok=True)
    written = []
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(SKILL.rglob("*")):
            if not path.is_file():
                continue
            if SKIP_DIRS.intersection(path.parts) or path.suffix in SKIP_SUFFIXES:
                continue
            arcname = path.relative_to(SKILL).as_posix()
            archive.write(path, arcname)
            written.append(arcname)
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(REPO / "build" / "workflowwright.zip"))
    args = ap.parse_args()

    out = Path(args.out)
    names = build(out)

    if "SKILL.md" not in names:
        # Refuse to ship an archive the uploader will reject. The failure mode
        # this guards against is silent: the file builds, uploads, and is turned
        # away for a reason that names a path rather than a cause.
        raise SystemExit(
            f"SKILL.md is not at the archive root (found: {names[:5]}). "
            "The upload would be rejected."
        )

    print(f"built {out} - {len(names)} files, {out.stat().st_size:,} bytes")
    print("  SKILL.md is at the archive root, as the uploader requires")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
