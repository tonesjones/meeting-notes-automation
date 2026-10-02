"""Zip the skill for upload to Claude (Cowork / claude.ai: Settings > Capabilities > Skills).

Run: python scripts/package_skill.py
Writes dist/meeting-to-obsidian.zip with the skill folder at the zip root.
Your local config.json is included (if present) so folder, tags and link settings carry over;
its vault_path is ignored in Cowork, where the vault is the folder you share with the session.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "meeting-to-obsidian"
OUT = ROOT / "dist" / "meeting-to-obsidian.zip"


def main() -> int:
    OUT.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(SKILL.rglob("*")):
            if path.is_dir() or "__pycache__" in path.parts:
                continue
            arcname = Path(SKILL.name) / path.relative_to(SKILL)
            zf.write(path, arcname.as_posix())
            print(f"  + {arcname.as_posix()}")
    print(f"Wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
