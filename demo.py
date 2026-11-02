"""A two minute tour. Run: python3 demo.py

Everything the demo stores is in memory and made up. It calls the same code the
tests call, and it runs the Stop hook the way Claude Code runs it: as a separate
process, with JSON on stdin and a transcript file on disk.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from reply_checker import Context, check
from study_engine.sample import load
from study_engine.stats import summarize
from study_engine.store import Refused

ROOT = Path(__file__).resolve().parent


def section(title: str) -> None:
    print(f"\n=== {title}\n")


def attempt_to(label: str, action) -> None:
    """Run one write and print what happened, the way the command line would."""
    print(f"$ {label}")
    try:
        print(f"  logged: {action()}")
    except Refused as refused:
        print(f"  REFUSED: {refused}")


def show_engine() -> None:
    store, clock, meta = load()
    deck, card = meta["deck"], meta["cards"][0]
    row_reduction = meta["ptypes"]["solve a 3 by 3 system by row reduction"]

    section("1. Study engine: a review with no confidence rating is refused")
    attempt_to("review card --rating 3", lambda: store.review(card, 3))
    attempt_to('review card --rating 3 --no-confidence ""', lambda: store.review(card, 3, no_confidence=""))
    attempt_to(
        "review card --rating 3 --confidence 7",
        lambda: {k: v for k, v in store.review(card, 3, confidence=7).items() if k in ("rating", "confidence", "correct")},
    )

    section("2. Rating and correctness are separate columns")
    print("A generous Good keeps the card on a kind schedule. The miss still counts as a miss.")
    attempt_to(
        "review card --rating 3 --confidence 8 --correct 0",
        lambda: {
            k: v for k, v in store.review(card, 3, confidence=8, correct=False).items()
            if k in ("rating", "confidence", "correct")
        },
    )

    section("3. A cold attempt must say which version of the problem it was")
    attempt_to(
        "attempt --ptype row-reduction --delay 2d --confidence 6",
        lambda: store.attempt(deck, "cold-solo", "sample", True, "2d", confidence=6, ptype=row_reduction),
    )
    attempt_to(
        'attempt --ptype row-reduction --delay 2d --confidence 6 --no-rung " "',
        lambda: store.attempt(deck, "cold-solo", "sample", True, "2d", confidence=6, ptype=row_reduction, no_rung=" "),
    )

    attempt_to(
        "attempt --ptype row-reduction --delay 2d --confidence 6 --rung inconsistent",
        lambda: store.attempt(
            deck, "cold-solo", "sample", True, "2d", confidence=6, ptype=row_reduction, rung="inconsistent"
        ),
    )

    section("4. Mastery is computed from attempts on every read, and never stored")
    print(f"{'state':<10}{'due':<13}{'next rung':<16}problem type")
    for row in store.statuses(deck):
        print(f"{row['state']:<10}{row['due']:<13}{row['next_rung'] or '-':<16}{row['name']}")
    plan = store.daily(deck)
    print(f"\nToday's cold slot is capped at {plan['cold_cap']}. Give: " + ", ".join(r["name"] for r in plan["give"]))
    for row in plan["ladder_short"]:
        print(f"LADDER SHORT, write its rungs first: {row['name']}")

    section("5. Numbers report their own sample size")
    summary = summarize(store, deck)
    calibration = summary["calibration"]
    print(f"accuracy {summary['accuracy']:.0%} over {summary['scored_items']} items: {summary['accuracy_verdict']}")
    print(f"mean confidence {calibration['mean_confidence']:.0%} against accuracy {calibration['accuracy']:.0%}"
          f" on {calibration['n']} rated items: {calibration['verdict']}")
    print(f"{'confidence':<12}{'n':<4}accuracy")
    for row in calibration["bins"]:
        accuracy = "-" if row["accuracy"] is None else f"{row['accuracy']:.0%}"
        print(f"{row['confidence']:<12}{row['n']:<4}{accuracy}")
    store.close()


BAD_REPLY = """Suppose we had $y = 2x$ instead.

$$y = 2x$$

$$2x = 4$$

So the answer is $2$."""

GOOD_REPLY = """Use your own line, drawn in the picture above.

$$y = 3x + 1$$

Set $y$ to 4 and read off the rest.

$$4 = 3x + 1$$

**So x is 1.** What does that point mean on the line?"""


def run_hook(transcript: Path, **extra) -> str:
    payload = json.dumps({"transcript_path": str(transcript), **extra})
    done = subprocess.run(
        [sys.executable, "-m", "reply_checker.stop_hook"],
        cwd=ROOT, input=payload, capture_output=True, text=True, env=dict(os.environ),
    )
    return done.stdout.strip()


def write_transcript(path: Path, reply: str, *tools: str) -> None:
    content = [{"type": "text", "text": reply}] + [{"type": "tool_use", "name": t, "input": {}} for t in tools]
    entries = [
        {"type": "user", "message": {"role": "user", "content": "the line is y = 3x + 1, what is x when y is 4"}},
        {"type": "assistant", "message": {"role": "assistant", "content": content}},
    ]
    path.write_text("\n".join(json.dumps(entry) for entry in entries) + "\n")


def show_checker() -> None:
    section("6. Reply checker: the Stop hook holds a bad reply")
    print("The student's message: the line is y = 3x + 1, what is x when y is 4\n")
    print("The reply, as the model wrote it:\n")
    print("\n".join("    " + line for line in BAD_REPLY.split("\n")))

    with tempfile.TemporaryDirectory() as folder:
        transcript = Path(folder) / "session.jsonl"
        write_transcript(transcript, BAD_REPLY)
        print("\nThe hook prints this, and Claude Code sends the reason back to the model:\n")
        decision = json.loads(run_hook(transcript))
        print(json.dumps({"decision": decision["decision"]}))
        print(decision["reason"])

        print("\nOn the next stop it stays silent, so a rule cannot trap a session:")
        print(f"  stop_hook_active=true prints: {run_hook(transcript, stop_hook_active=True)!r}")

        section("7. The corrected reply, with a picture shown this turn, passes")
        print("\n".join("    " + line for line in GOOD_REPLY.split("\n")))
        write_transcript(transcript, GOOD_REPLY, "show_widget")
        print(f"\nThe hook prints: {run_hook(transcript)!r}")

    findings = check(GOOD_REPLY, Context(picture_shown=True, sources="the line is y = 3x + 1"))
    print(f"All rules, STOP and STYLE: {len(findings)} findings")


def main() -> int:
    print("Education Hub demo. All data is made up: sample_data/sample_course.json, a fake course in the year 2030.")
    show_engine()
    show_checker()
    print("\nNext: python3 tools/mutation_check.py shows each rule's test failing when the rule is removed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
