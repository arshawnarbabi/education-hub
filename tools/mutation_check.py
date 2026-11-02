"""Prove the tests can fail. Run: python3 tools/mutation_check.py

A passing test proves little if it would also pass with the rule deleted. So for
each mechanism this copies the repo to a temp folder, removes the mechanism with
one exact text replacement, and runs the suite that claims to cover it. The
mechanism counts as proven only if that suite now fails. A replacement whose text
no longer exists stops the run, so this list cannot rot quietly.

Exit code 0 when every mutant is caught and the unmodified code passes.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IGNORE = shutil.ignore_patterns(".git", ".venv", "__pycache__", "*.db")


@dataclass(frozen=True)
class Mutant:
    name: str
    file: str
    old: str
    new: str
    suite: str


MUTANTS = [
    Mutant(
        "review with no confidence rating",
        "study_engine/store.py",
        "confidence, no_confidence = self._check_confidence(confidence, no_confidence, required=True)",
        "confidence, no_confidence = self._check_confidence(confidence, no_confidence, required=False)",
        "tests.test_engine.ConfidenceRule",
    ),
    Mutant(
        "blank reason for no confidence",
        "study_engine/store.py",
        'if no_confidence is not None and not no_confidence.strip():',
        "if False:",
        "tests.test_engine.ConfidenceRule",
    ),
    Mutant(
        "delayed attempt with no rating",
        "study_engine/store.py",
        "confidence, no_confidence, required=needs_confidence(source, delay)",
        "confidence, no_confidence, required=False",
        "tests.test_engine.ConfidenceRule",
    ),
    Mutant(
        "generous rating leaks into correct",
        "study_engine/store.py",
        "(card_id, self._now(), stored_rating, int(correct), confidence",
        "(card_id, self._now(), stored_rating, int(stored_rating > 1), confidence",
        "tests.test_engine.RatingAndCorrectStayApart",
    ),
    Mutant(
        "doubt words ignored",
        "study_engine/store.py",
        "stored_rating = min(rating, 2) if doubt else rating",
        "stored_rating = rating",
        "tests.test_engine.RatingAndCorrectStayApart",
    ),
    Mutant(
        "cold attempt with no rung",
        "study_engine/store.py",
        "if cold and ladder:",
        "if False:",
        "tests.test_engine.RungRule",
    ),
    Mutant(
        "blank reason for no rung",
        "study_engine/store.py",
        "if not no_rung.strip():",
        "if False:",
        "tests.test_engine.RungRule",
    ),
    Mutant(
        "solid without a time gap",
        "study_engine/mastery.py",
        "if spaced and varied:",
        "if varied:",
        "tests.test_engine.SolidStatus",
    ),
    Mutant(
        "solid without variety",
        "study_engine/mastery.py",
        "if spaced and varied:",
        "if spaced:",
        "tests.test_engine.SolidStatus",
    ),
    Mutant(
        "a miss does not reset the count",
        "study_engine/mastery.py",
        "last_miss = max((i for i, a in enumerate(cold) if not a.correct), default=-1)",
        "last_miss = -1",
        "tests.test_engine.SolidStatus",
    ),
    Mutant(
        "short ladder finding removed",
        "study_engine/mastery.py",
        "return solved and live_rungs < need and not declared_ok",
        "return False",
        "tests.test_engine.LadderShort",
    ),
    Mutant(
        "small samples stated as fact",
        "study_engine/stats.py",
        'return "enough to read" if n >= MIN_N_TO_CLAIM else',
        'return "enough to read" if n >= 0 else',
        "tests.test_engine.Stats",
    ),
    Mutant(
        "explanation with no picture",
        "reply_checker/rules.py",
        'if explanation and not context.picture_shown and not declared("no-picture"):',
        "if False:",
        "tests.test_checker.NoPicture",
    ),
    Mutant(
        "blank declared reason accepted",
        "reply_checker/rules.py",
        "if not _reason_ok(decl[kind]):",
        "if False:",
        "tests.test_checker.NoPicture",
    ),
    Mutant(
        "recall questions held as explanations",
        "reply_checker/rules.py",
        "return explains(reply) and not asks_only(reply) and not about_the_tool(context.prompt)",
        "return explains(reply) and not about_the_tool(context.prompt)",
        "tests.test_checker.QuestionsAreNotExplanations",
    ),
    Mutant(
        "any use of 'the system' exempts a reply",
        "reply_checker/rules.py",
        r'r"(?<!solve )(?<!solving )\bthe system\b(?!\s+of\b)|"',
        r'r"\bthe system\b|"',
        "tests.test_checker.AboutTheTool",
    ),
    Mutant(
        "made-up curve allowed",
        "reply_checker/rules.py",
        'if made and not declared("made-up-example"):',
        "if False:",
        "tests.test_checker.MadeUpExamples",
    ),
    Mutant(
        "rewritten curve counted as foreign",
        "reply_checker/curves.py",
        "if curve.label not in labels and not any(same_curve(curve, source) for source in own)",
        "if curve.label not in labels",
        "tests.test_checker.MadeUpExamples",
    ),
    Mutant(
        "ast whitelist removed",
        "reply_checker/curves.py",
        "if not isinstance(node, _ALLOWED_NODES):",
        "if False:",
        "tests.test_checker.CurveReading",
    ),
    Mutant(
        "hook holds forever",
        "reply_checker/stop_hook.py",
        'if data.get("stop_hook_active"):',
        "if False:",
        "tests.test_hook.StopHook",
    ),
    Mutant(
        "hook ignores the rules",
        "reply_checker/stop_hook.py",
        "if not held:",
        "if True:",
        "tests.test_hook.StopHook",
    ),
    Mutant(
        "hook crash goes unlogged",
        "reply_checker/stop_hook.py",
        "        _log_crash(stdin_text)\n",
        "",
        "tests.test_hook.StopHook",
    ),
]


def run_suite(folder: Path, suite: str) -> bool:
    done = subprocess.run(
        [sys.executable, "-m", "unittest", "-q", suite], cwd=folder, capture_output=True, text=True
    )
    return done.returncode == 0


def try_mutant(mutant: Mutant) -> bool:
    """True when the suite fails with the mechanism removed."""
    with tempfile.TemporaryDirectory() as folder:
        copy = Path(folder) / "repo"
        shutil.copytree(ROOT, copy, ignore=IGNORE)
        target = copy / mutant.file
        source = target.read_text(encoding="utf-8")
        if source.count(mutant.old) != 1:
            raise SystemExit(f"stale mutant, text appears {source.count(mutant.old)} times: {mutant.name}")
        target.write_text(source.replace(mutant.old, mutant.new), encoding="utf-8")
        return not run_suite(copy, mutant.suite)


def main() -> int:
    suites = sorted({mutant.suite for mutant in MUTANTS})
    for suite in suites:
        if not run_suite(ROOT, suite):
            print(f"unmodified code fails {suite}, so nothing below would mean anything")
            return 1
    print(f"Unmodified code: {len(suites)} suites pass.\n")
    caught = 0
    for mutant in MUTANTS:
        ok = try_mutant(mutant)
        caught += ok
        print(f"{'caught' if ok else 'MISSED':<8}{mutant.name}  ({mutant.suite.rsplit('.', 1)[-1]})")
    print(f"\n{caught} of {len(MUTANTS)} mutants caught.")
    return 0 if caught == len(MUTANTS) else 1


if __name__ == "__main__":
    sys.exit(main())
