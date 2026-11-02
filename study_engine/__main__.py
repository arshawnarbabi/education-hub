"""Command line for the study engine. Run: python3 -m study_engine --help

Exit codes: 0 done, 2 refused or bad input. A refusal goes to stderr and stores nothing.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from .stats import summarize
from .store import Refused, Store


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="study_engine", description=__doc__)
    parser.add_argument("--db", default=os.environ.get("STUDY_DB", "study.db"), help="SQLite file (default study.db)")
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="add a card")
    add.add_argument("--deck", required=True)
    add.add_argument("--front", required=True)
    add.add_argument("--back", required=True)
    add.add_argument("--from-attempt", type=int, help="the miss this card came from")

    sub.add_parser("due", help="cards due now").add_argument("--deck")

    review = sub.add_parser("review", help="score a card")
    review.add_argument("card", type=int)
    review.add_argument("--rating", type=int, required=True, choices=[1, 2, 3, 4])
    review.add_argument("--confidence", type=int)
    review.add_argument("--no-confidence", help="the reason there is no rating")
    review.add_argument("--correct", type=int, choices=[0, 1])
    review.add_argument("--doubt", help="the student's own words of doubt")

    attempt = sub.add_parser("attempt", help="log a scored item that is not a card")
    attempt.add_argument("--deck", required=True)
    attempt.add_argument("--source", required=True)
    attempt.add_argument("--prompt", required=True)
    attempt.add_argument("--correct", type=int, choices=[0, 1], required=True)
    attempt.add_argument("--delay", required=True, help="cold, same-session, <N>h or <N>d")
    attempt.add_argument("--confidence", type=int)
    attempt.add_argument("--no-confidence")
    attempt.add_argument("--topic")
    attempt.add_argument("--ptype", type=int)
    attempt.add_argument("--rung")
    attempt.add_argument("--no-rung", help="the reason no rung of the ladder fits")
    attempt.add_argument("--doubt")

    ptype = sub.add_parser("ptype-add", help="register a kind of whole problem")
    ptype.add_argument("--deck", required=True)
    ptype.add_argument("--section", required=True)
    ptype.add_argument("--name", required=True)
    ptype.add_argument("--since")

    rung = sub.add_parser("rung-add", help="add one way a problem type can be asked")
    rung.add_argument("ptype", type=int)
    rung.add_argument("--key", required=True)
    rung.add_argument("--label", required=True)
    rung.add_argument("--base", action="store_true")

    ladder_ok = sub.add_parser("ladder-ok", help="declare why a short ladder is fine")
    ladder_ok.add_argument("ptype", type=int)
    ladder_ok.add_argument("--reason", required=True)

    sub.add_parser("status", help="mastery of every problem type").add_argument("--deck")
    sub.add_parser("daily", help="today's slot").add_argument("--deck", required=True)
    sub.add_parser("stats", help="accuracy and calibration").add_argument("--deck")
    sub.add_parser("weak", help="recent misses by topic").add_argument("--deck")
    return parser


def run(args: argparse.Namespace, store: Store):
    command = args.command
    if command == "add":
        return {"card": store.add_card(args.deck, args.front, args.back, from_attempt=args.from_attempt)}
    if command == "due":
        return [dict(row) for row in store.due(args.deck)]
    if command == "review":
        correct = None if args.correct is None else bool(args.correct)
        return store.review(args.card, args.rating, args.confidence, args.no_confidence, correct, args.doubt)
    if command == "attempt":
        return {
            "attempt": store.attempt(
                args.deck, args.source, args.prompt, bool(args.correct), args.delay, args.confidence,
                args.no_confidence, args.topic, args.ptype, args.rung, args.no_rung, args.doubt,
            )
        }
    if command == "ptype-add":
        return {"ptype": store.add_ptype(args.deck, args.section, args.name, args.since)}
    if command == "rung-add":
        store.add_rung(args.ptype, args.key, args.label, args.base)
        return {"ptype": args.ptype, "rung": args.key}
    if command == "ladder-ok":
        store.declare_ladder_ok(args.ptype, args.reason)
        return {"ptype": args.ptype, "ladder_ok": args.reason}
    if command == "status":
        return store.statuses(args.deck)
    if command == "daily":
        return store.daily(args.deck)
    if command == "stats":
        return summarize(store, args.deck)
    return store.weak(args.deck)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = Store(args.db)
    try:
        print(json.dumps(run(args, store), indent=2, default=str))
    except Refused as refused:
        print(f"REFUSED: {refused}", file=sys.stderr)
        return 2
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
