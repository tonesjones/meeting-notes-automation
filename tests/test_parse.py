"""Regression test for the recap parser.

Run: python tests/test_parse.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from capture import parse_recap, render_markdown  # noqa: E402


def main() -> int:
    fixtures = ROOT / "tests" / "fixtures"
    raw = (fixtures / "sample_recap.txt").read_text(encoding="utf-8")
    expected = (fixtures / "sample_recap.expected.md").read_text(encoding="utf-8")

    recap = parse_recap(raw)
    actual = render_markdown(recap, tags=["meeting", "customer"])

    # Normalize trailing whitespace for compare.
    def norm(s: str) -> str:
        return "\n".join(line.rstrip() for line in s.rstrip().splitlines())

    if norm(actual) == norm(expected):
        print("PASS")
        return 0

    print("FAIL — diff:")
    import difflib
    for line in difflib.unified_diff(
        norm(expected).splitlines(),
        norm(actual).splitlines(),
        fromfile="expected",
        tofile="actual",
        lineterm="",
    ):
        print(line)
    return 1


if __name__ == "__main__":
    sys.exit(main())
