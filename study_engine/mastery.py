"""Mastery of a whole-problem type, computed from attempts and never stored.

Everything in this file is pure: no database, no clock, no I/O. The store passes
rows in and a status comes out, so the rules can be tested exhaustively and a
status can never drift from the attempts behind it.

Vocabulary:
    problem type   a kind of whole problem an exam can ask
    rung           one way that type can be asked (the variant ladder)
    cold attempt   a full attempt made a day or more after last seeing the material
    solid          see solid_status() below
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

SOLID_GAP_DAYS = 6       # two right cold attempts must be at least this far apart
VARIANT_GAP_DAYS = 2     # spaced enough, but the same rung twice: try another soon
MAINTAIN_GAP_DAYS = 14   # a solid type comes back this often

BASE = "base"
_COLD_DELAY = re.compile(r"^(\d+(?:\.\d+)?)d$")


def is_cold(delay: str | None) -> bool:
    """A delay of one day or more. '1d' is cold; '12h', 'same-session' and 'none' are not."""
    match = _COLD_DELAY.match(delay or "")
    return bool(match) and float(match.group(1)) >= 1


@dataclass(frozen=True)
class Attempt:
    """One scored attempt linked to a problem type, as the status rules see it."""

    day: date
    correct: bool
    delay: str
    rung: str = BASE     # the rung's key, or BASE, or a unique label for an unnamed one
    shaky: bool = False  # right, but the student said in words that they doubted it


@dataclass(frozen=True)
class Status:
    state: str  # new | missed | building | solid
    due: date
    need: str


def scored(attempts: list[Attempt]) -> list[Attempt]:
    """Drop shaky rights. A right answer the student doubted is neither a pass nor a miss."""
    return [a for a in attempts if not a.shaky]


def right_since_last_miss(attempts: list[Attempt]) -> list[Attempt]:
    cold = [a for a in scored(attempts) if is_cold(a.delay)]
    last_miss = max((i for i, a in enumerate(cold) if not a.correct), default=-1)
    return cold[last_miss + 1:]


def solid_status(attempts: list[Attempt], since: date) -> Status:
    """The status of one type. attempts must be oldest first.

    Solid means: since the last cold miss, at least two right cold attempts, at
    least SOLID_GAP_DAYS apart, covering at least two different rungs, at least
    one of which is not the base. One miss resets the count. The rule is about
    spacing and variety because a type that was only ever solved the same way in
    one sitting tells you little about what happens on an exam.
    """
    cold = [a for a in scored(attempts) if is_cold(a.delay)]
    if not cold:
        return Status("new", since + timedelta(days=1), "first cold attempt")
    if not cold[-1].correct:
        return Status("missed", cold[-1].day + timedelta(days=1), "cold attempt again")

    right = right_since_last_miss(attempts)
    first, last = right[0].day, right[-1].day
    spaced = len(right) >= 2 and (last - first).days >= SOLID_GAP_DAYS
    rungs = {a.rung for a in right}
    varied = len(rungs) >= 2 and any(rung != BASE for rung in rungs)

    if spaced and varied:
        return Status("solid", last + timedelta(days=MAINTAIN_GAP_DAYS), "maintenance")
    if not spaced:
        due = max(first + timedelta(days=SOLID_GAP_DAYS), last + timedelta(days=1))
        need = f"second cold attempt, {SOLID_GAP_DAYS}+ days after the first"
        return Status("building", due, need + ("" if varied else ", on a different rung"))
    return Status("building", last + timedelta(days=VARIANT_GAP_DAYS), "a different rung")


def base_solved(attempts: list[Attempt]) -> bool:
    """The base went right cold at least once. Harder rungs wait for this."""
    return any(a.correct and is_cold(a.delay) and a.rung == BASE for a in scored(attempts))


def next_rung(attempts: list[Attempt], ladder: list[str]) -> str | None:
    """The rung to give next, in ladder order, or None.

    ladder holds the non-base keys. Prefer a rung never tried, then the rung
    tried longest ago among those not yet right since the last miss, then the
    rung done longest ago. None before the base has gone right cold.
    """
    if not ladder or not base_solved(attempts):
        return None
    done = {a.rung for a in right_since_last_miss(attempts)}
    last_seen: dict[str, date] = {}
    for attempt in scored(attempts):
        last_seen[attempt.rung] = attempt.day
    pending = [rung for rung in ladder if rung not in done]
    never = [rung for rung in pending if rung not in last_seen]
    if never:
        return never[0]
    pool = pending or ladder
    return min(pool, key=lambda rung: last_seen.get(rung, date.min))


def ladder_short(live_rungs: int, solved: bool, need: int, declared_ok: bool) -> bool:
    """A type whose base is solved and whose ladder has too few rungs to practice on."""
    return solved and live_rungs < need and not declared_ok


URGENCY = {"missed": 0, "new": 1, "building": 2, "solid": 3}


def daily_cap(statuses: list[Status], today: date, normal: int = 2, pressed: int = 3) -> int:
    """How many cold problems today: more while anything is new or overdue, never unbounded."""
    pressing = any(s.state == "new" or s.due < today for s in statuses)
    return pressed if pressing else normal
