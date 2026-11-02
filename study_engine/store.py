"""The item store: cards, reviews, attempts and problem types in SQLite.

Scheduling is the real FSRS algorithm from the open source `fsrs` package and is
not reimplemented here. What this layer adds:

* Two columns a flashcard app does not keep. `confidence` is a 0 to 10 rating
  given before the answer key is seen. `correct` is a strict 0 or 1 kept apart
  from the FSRS rating, so a generous rating can steer scheduling without
  inflating accuracy.
* Refusals. A write that breaks a rule raises Refused and stores nothing. Where
  a rule can legitimately not apply, there is a declared way out that needs a
  reason, and a blank reason is refused too.

Every status is computed from rows on read (see mastery.py), so there is no
stored status to go stale.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Callable

from fsrs import Card, Rating, Scheduler

from . import mastery

DESIRED_RETENTION = 0.9
LADDER_MIN_RUNGS = 4
DAILY_CARDS = 8

RATINGS = {1: "Again", 2: "Hard", 3: "Good", 4: "Easy"}
DELAY_RE = re.compile(r"^(cold|same-session|\d+(\.\d+)?[hd])$")
TIMED_DELAY_RE = re.compile(r"^\d+(\.\d+)?[hd]$")
RUNG_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}$")
CLOSED_BOOK_SOURCES = ("recall", "unassisted", "quiz", "mock", "exam", "cold-solo")

SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deck TEXT NOT NULL, front TEXT NOT NULL, back TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT '', created TEXT NOT NULL,
    fsrs_state TEXT NOT NULL, due TEXT NOT NULL,
    suspended INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_cards_due ON cards(due);

CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    ts TEXT NOT NULL,
    rating INTEGER NOT NULL,      -- FSRS 1 to 4, drives scheduling, may be generous
    correct INTEGER NOT NULL,     -- strict 0 or 1, feeds accuracy, never generous
    confidence INTEGER,           -- 0 to 10, given before the key
    no_conf_reason TEXT,          -- why there is no rating, when there is none
    doubt TEXT,                   -- the student's words of doubt, verbatim
    elapsed_ms INTEGER
);

CREATE TABLE IF NOT EXISTS ptypes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deck TEXT NOT NULL, section TEXT NOT NULL, name TEXT NOT NULL,
    since TEXT NOT NULL,          -- first practiced, YYYY-MM-DD
    retired INTEGER NOT NULL DEFAULT 0,
    ladder_ok TEXT                -- declared reason a short ladder is fine
);

CREATE TABLE IF NOT EXISTS rungs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ptype_id INTEGER NOT NULL REFERENCES ptypes(id),
    key TEXT NOT NULL, label TEXT NOT NULL,
    base INTEGER NOT NULL DEFAULT 0,
    retired INTEGER NOT NULL DEFAULT 0,
    UNIQUE(ptype_id, key)
);

CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    deck TEXT NOT NULL, source TEXT NOT NULL, topic TEXT,
    prompt TEXT NOT NULL,
    correct INTEGER NOT NULL,
    confidence INTEGER, no_conf_reason TEXT, doubt TEXT,
    delay TEXT NOT NULL,          -- cold | same-session | <N>h | <N>d
    ptype_id INTEGER REFERENCES ptypes(id),
    rung_key TEXT,
    no_rung_reason TEXT,          -- declared reason no rung of the ladder fits
    card_id INTEGER REFERENCES cards(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_attempts_deck ON attempts(deck);
CREATE INDEX IF NOT EXISTS idx_attempts_ptype ON attempts(ptype_id);
"""


class Refused(ValueError):
    """A write that breaks a rule. Nothing was stored."""

    def __init__(self, why: str):
        super().__init__(f"{why} Nothing was logged.")


def parse_ts(ts: str) -> datetime:
    """Read a stored time. Accepts a trailing Z, which fromisoformat rejects before Python 3.11."""
    text = ts.strip()
    return datetime.fromisoformat(text[:-1] + "+00:00" if text[-1:] in "Zz" else text)


def needs_confidence(source: str, delay: str) -> bool:
    """A delayed or closed-book item needs a rating, or a stated reason for not having one.

    Same-session lesson checks and 'cold' prequestions on new material are left
    alone: rating them would add friction with nothing to calibrate against.
    """
    if TIMED_DELAY_RE.match(delay):
        return True
    lowered = source.lower()
    if lowered.startswith(CLOSED_BOOK_SOURCES):
        return not (delay == "same-session" and lowered.startswith("quiz"))
    return False


class Store:
    """All reads and writes. clock and tz are injectable so tests and the demo are deterministic."""

    def __init__(
        self,
        path: str = ":memory:",
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        tz: tzinfo | None = None,
        fuzz: bool = True,
    ):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self.clock = clock
        self.tz = tz
        self.scheduler = Scheduler(desired_retention=DESIRED_RETENTION, enable_fuzzing=fuzz)

    def close(self) -> None:
        self.conn.close()

    def _now(self) -> str:
        return self.clock().astimezone(timezone.utc).isoformat()

    def _local_date(self, ts: str) -> date:
        return parse_ts(ts).astimezone(self.tz).date()

    def today(self) -> date:
        return self.clock().astimezone(self.tz).date()

    # ------------------------------------------------------------------ cards

    def add_card(self, deck: str, front: str, back: str, source: str = "", from_attempt: int | None = None) -> int:
        """Add a card. from_attempt links the miss that exposed the gap."""
        if from_attempt is not None and not self.conn.execute(
            "SELECT 1 FROM attempts WHERE id=?", (from_attempt,)
        ).fetchone():
            raise Refused(f"no attempt {from_attempt}.")
        now = self.clock()
        card = Card(due=now)
        card_id = self.conn.execute(
            "INSERT INTO cards (deck, front, back, source, created, fsrs_state, due) VALUES (?,?,?,?,?,?,?)",
            (deck, front, back, source, self._now(), json.dumps(card.to_dict()), card.due.isoformat()),
        ).lastrowid
        if from_attempt is not None:
            self.conn.execute("UPDATE attempts SET card_id=? WHERE id=?", (card_id, from_attempt))
        self.conn.commit()
        return card_id

    def due(self, deck: str | None = None) -> list[sqlite3.Row]:
        sql = "SELECT id, deck, front, due FROM cards WHERE suspended=0"
        args: list = []
        if deck:
            sql += " AND deck=?"
            args.append(deck)
        rows = self.conn.execute(sql + " ORDER BY due", args).fetchall()
        now = self.clock()
        return [row for row in rows if parse_ts(row["due"]) <= now]

    def review(
        self,
        card_id: int,
        rating: int,
        confidence: int | None = None,
        no_confidence: str | None = None,
        correct: bool | None = None,
        doubt: str | None = None,
        elapsed_ms: int | None = None,
    ) -> dict:
        """Score one card. Every card review needs a confidence rating or a stated reason."""
        row = self.conn.execute("SELECT * FROM cards WHERE id=?", (card_id,)).fetchone()
        if row is None:
            raise Refused(f"no card {card_id}.")
        if rating not in RATINGS:
            raise Refused("rating must be 1 to 4.")
        confidence, no_confidence = self._check_confidence(confidence, no_confidence, required=True)
        doubt = (doubt or "").strip() or None

        stored_rating = min(rating, 2) if doubt else rating  # doubt words only ever lower it, to Hard at most
        if correct is None:
            correct = stored_rating > 1

        now = self.clock()
        card = Card.from_dict(json.loads(row["fsrs_state"]))
        updated, _ = self.scheduler.review_card(card, Rating(stored_rating), review_datetime=now)
        self.conn.execute(
            "UPDATE cards SET fsrs_state=?, due=? WHERE id=?",
            (json.dumps(updated.to_dict()), updated.due.isoformat(), card_id),
        )
        self.conn.execute(
            "INSERT INTO reviews (card_id, ts, rating, correct, confidence, no_conf_reason, doubt, elapsed_ms)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (card_id, self._now(), stored_rating, int(correct), confidence, no_confidence, doubt, elapsed_ms),
        )
        self.conn.commit()
        return {
            "card": card_id,
            "rating": RATINGS[stored_rating],
            "correct": int(correct),
            "confidence": confidence,
            "next_due": updated.due.isoformat(),
            "stability_days": round(updated.stability or 0, 2),
        }

    @staticmethod
    def _check_confidence(confidence, no_confidence, required: bool):
        if confidence is not None and not 0 <= confidence <= 10:
            raise Refused("confidence must be 0 to 10.")
        if no_confidence is not None and not no_confidence.strip():
            raise Refused("a reason for no confidence rating cannot be blank.")
        if confidence is None and no_confidence is None and required:
            raise Refused(
                "confidence missing: give a 0 to 10 rating from before the key was seen,"
                " or state why there is none."
            )
        return confidence, None if confidence is not None else no_confidence

    # ------------------------------------------------------------------ problem types

    def add_ptype(self, deck: str, section: str, name: str, since: str | None = None) -> int:
        """Register a kind of whole problem. It takes no prior attempts: a first miss still needs to come back."""
        since = since or self.today().isoformat()
        date.fromisoformat(since)
        ptype_id = self.conn.execute(
            "INSERT INTO ptypes (deck, section, name, since) VALUES (?,?,?,?)", (deck, section, name, since)
        ).lastrowid
        self.conn.commit()
        return ptype_id

    def add_rung(self, ptype_id: int, key: str, label: str, base: bool = False) -> None:
        self._live_ptype(ptype_id)
        if not RUNG_KEY_RE.match(key):
            raise Refused(f"rung key {key!r} must be a lowercase slug.")
        if base and self.conn.execute(
            "SELECT 1 FROM rungs WHERE ptype_id=? AND base=1 AND retired=0", (ptype_id,)
        ).fetchone():
            raise Refused(f"problem type {ptype_id} already has a base rung.")
        self.conn.execute(
            "INSERT INTO rungs (ptype_id, key, label, base) VALUES (?,?,?,?)", (ptype_id, key, label, int(base))
        )
        self.conn.commit()

    def declare_ladder_ok(self, ptype_id: int, reason: str) -> None:
        """The way out of the short ladder finding, for a type that really has few ways to be asked."""
        if not reason.strip():
            raise Refused("a reason for a short ladder cannot be blank.")
        self._live_ptype(ptype_id)
        if self._live_rung_count(ptype_id) >= LADDER_MIN_RUNGS:
            raise Refused(f"problem type {ptype_id} already has {LADDER_MIN_RUNGS} rungs; there is nothing to excuse.")
        self.conn.execute("UPDATE ptypes SET ladder_ok=? WHERE id=?", (reason.strip(), ptype_id))
        self.conn.commit()

    def _live_ptype(self, ptype_id: int) -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM ptypes WHERE id=? AND retired=0", (ptype_id,)).fetchone()
        if row is None:
            raise Refused(f"no live problem type {ptype_id}.")
        return row

    def _rungs(self, ptype_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT key, label, base FROM rungs WHERE ptype_id=? AND retired=0 ORDER BY id", (ptype_id,)
        ).fetchall()

    def _live_rung_count(self, ptype_id: int) -> int:
        return sum(1 for rung in self._rungs(ptype_id) if not rung["base"])

    # ------------------------------------------------------------------ attempts

    def attempt(
        self,
        deck: str,
        source: str,
        prompt: str,
        correct: bool,
        delay: str,
        confidence: int | None = None,
        no_confidence: str | None = None,
        topic: str | None = None,
        ptype: int | None = None,
        rung: str | None = None,
        no_rung: str | None = None,
        doubt: str | None = None,
    ) -> int:
        """Log a scored item that is not a card: a quiz question, a checkpoint, a whole problem."""
        if not DELAY_RE.match(delay or ""):
            raise Refused(f"delay {delay!r} must be cold, same-session, <N>h or <N>d.")
        confidence, no_confidence = self._check_confidence(
            confidence, no_confidence, required=needs_confidence(source, delay)
        )
        why = self._rung_refusal(ptype, rung, no_rung, delay)
        if why:
            raise Refused(why)
        attempt_id = self.conn.execute(
            "INSERT INTO attempts (ts, deck, source, topic, prompt, correct, confidence, no_conf_reason, doubt,"
            " delay, ptype_id, rung_key, no_rung_reason) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                self._now(), deck, source, topic, prompt, int(correct), confidence, no_confidence,
                (doubt or "").strip() or None, delay, ptype, rung, (no_rung or "").strip() or None,
            ),
        ).lastrowid
        self.conn.commit()
        return attempt_id

    def _rung_refusal(self, ptype, rung, no_rung, delay) -> str | None:
        """Why this attempt may not be logged as given, or None.

        A cold attempt of a type with a ladder has to say which rung it was, or
        declare why none fits. Without this, an attempt at a harder version with
        no rung named is scored as the base and the status is silently wrong.
        The declaration is checked against the rest of the call, so it cannot
        contradict what the call says.
        """
        if ptype is None:
            if rung is not None or no_rung is not None:
                return "a rung or a declared no-rung needs a problem type."
            return None
        self._live_ptype(ptype)
        cold = mastery.is_cold(delay)
        if delay == "cold":
            return "a problem type's attempt needs a real delay (<N>d or <N>h); 'cold' means a prequestion."
        ladder = self._rungs(ptype)
        keys = [row["key"] for row in ladder]
        if no_rung is not None:
            if not no_rung.strip():
                return "a reason for no rung cannot be blank."
            if rung is not None:
                return f"no-rung says none fits, but {rung} names one."
            if not cold:
                return f"no-rung is for a cold attempt; at delay {delay} no rung is needed."
            if not ladder:
                return f"problem type {ptype} has no rungs yet, so nothing needs excusing."
            return None
        if rung is not None:
            if rung not in keys:
                return f"unknown rung {rung!r}; valid: {', '.join(keys) or 'none'}."
            return None
        if cold and ladder:
            return (
                f"a cold attempt of problem type {ptype} must name its rung, one of: {', '.join(keys)}."
                " If none fits, declare why."
            )
        return None

    def _mastery_attempts(self, ptype_id: int) -> list[mastery.Attempt]:
        base_keys = {row["key"] for row in self._rungs(ptype_id) if row["base"]}
        rows = self.conn.execute("SELECT * FROM attempts WHERE ptype_id=? ORDER BY ts, id", (ptype_id,)).fetchall()
        out = []
        for row in rows:
            if row["no_rung_reason"]:
                rung = f"unnamed-{row['id']}"  # different from every other attempt, so it counts as variety
            elif row["rung_key"] and row["rung_key"] not in base_keys:
                rung = row["rung_key"]
            else:
                rung = mastery.BASE
            out.append(
                mastery.Attempt(
                    day=self._local_date(row["ts"]),
                    correct=bool(row["correct"]),
                    delay=row["delay"],
                    rung=rung,
                    shaky=bool(row["correct"] and row["doubt"]),
                )
            )
        return out

    def status(self, ptype_id: int) -> dict:
        row = self._live_ptype(ptype_id)
        attempts = self._mastery_attempts(ptype_id)
        state = mastery.solid_status(attempts, date.fromisoformat(row["since"]))
        ladder = [r["key"] for r in self._rungs(ptype_id) if not r["base"]]
        return {
            "id": ptype_id,
            "section": row["section"],
            "name": row["name"],
            "state": state.state,
            "due": state.due.isoformat(),
            "need": state.need,
            "next_rung": mastery.next_rung(attempts, ladder),
            "ladder_short": mastery.ladder_short(
                len(ladder), mastery.base_solved(attempts), LADDER_MIN_RUNGS, bool(row["ladder_ok"])
            ),
        }

    def statuses(self, deck: str | None = None) -> list[dict]:
        sql, args = "SELECT id FROM ptypes WHERE retired=0", []
        if deck:
            sql, args = sql + " AND deck=?", [deck]
        rows = [self.status(row["id"]) for row in self.conn.execute(sql + " ORDER BY id", args).fetchall()]
        return sorted(rows, key=lambda r: (mastery.URGENCY[r["state"]], r["due"]))

    def daily(self, deck: str) -> dict:
        """Today's slot: are cards due, and which cold problems, capped so a backlog never becomes a wall."""
        today = self.today()
        rows = self.statuses(deck)
        states = [mastery.Status(r["state"], date.fromisoformat(r["due"]), r["need"]) for r in rows]
        cap = mastery.daily_cap(states, today)
        done_today = sum(
            1
            for row in self.conn.execute(
                "SELECT ts, delay FROM attempts WHERE deck=? AND ptype_id IS NOT NULL", (deck,)
            ).fetchall()
            if mastery.is_cold(row["delay"]) and self._local_date(row["ts"]) == today
        )
        due = [r for r in rows if date.fromisoformat(r["due"]) <= today]
        return {
            "cards_due": bool(self.due(deck)),
            "cold_cap": cap,
            "cold_done_today": done_today,
            "give": due[: max(0, cap - done_today)],
            "ladder_short": [r for r in rows if r["ladder_short"]],
        }

    # ------------------------------------------------------------------ what the numbers say

    def _scored(self, deck: str | None) -> list[sqlite3.Row]:
        where, args = (" WHERE deck=?", [deck]) if deck else ("", [])
        return self.conn.execute(
            "SELECT deck, correct, confidence, source, topic, delay, ts, card_id, kind FROM ("
            " SELECT c.deck deck, r.correct correct, r.confidence confidence, 'review' source, NULL topic,"
            "        NULL delay, r.ts ts, r.card_id card_id, 'review' kind"
            " FROM reviews r JOIN cards c ON c.id = r.card_id"
            " UNION ALL"
            " SELECT deck, correct, confidence, source, topic, delay, ts, card_id, 'attempt' FROM attempts"
            ")" + where,
            args,
        ).fetchall()

    def weak(self, deck: str | None = None, days: int = 14) -> list[dict]:
        """Recent misses by topic, each flagged if no card was made from it yet."""
        since = self.clock() - timedelta(days=days)
        topics: dict[str, dict] = {}
        for row in self._scored(deck):
            if row["kind"] != "attempt" or not row["topic"] or parse_ts(row["ts"]) < since:
                continue
            item = topics.setdefault(row["topic"], {"topic": row["topic"], "misses": 0, "right": 0, "no_card": 0})
            if row["correct"]:
                item["right"] += 1
            else:
                item["misses"] += 1
                item["no_card"] += row["card_id"] is None
        return sorted((t for t in topics.values() if t["misses"]), key=lambda t: (-t["misses"], t["topic"]))
