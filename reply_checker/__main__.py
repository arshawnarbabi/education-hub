"""Check one reply from the command line: python3 -m reply_checker reply.md [--sources problem.txt]

Prints every finding, STOP and STYLE. Exit code 1 when a STOP finding is present, else 0.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .rules import Context, check


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="reply_checker", description=__doc__)
    parser.add_argument("reply", help="a markdown file, or - for stdin")
    parser.add_argument("--sources", help="a file with the problem's own text")
    parser.add_argument("--picture", action="store_true", help="a picture was shown with this reply")
    args = parser.parse_args(argv)

    reply = sys.stdin.read() if args.reply == "-" else Path(args.reply).read_text(encoding="utf-8")
    sources = Path(args.sources).read_text(encoding="utf-8") if args.sources else ""
    findings = check(reply, Context(picture_shown=args.picture, sources=sources))
    for finding in findings:
        print(("STOP   " if finding.is_stop else "STYLE  ") + str(finding))
    if not findings:
        print("clean")
    return 1 if any(finding.is_stop for finding in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
