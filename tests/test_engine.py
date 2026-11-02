"""Study engine: each refusal has a planted violation, a compliant twin and a blank-reason case."""
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from study_engine import mastery
from study_engine.mastery import Attempt, solid_status
from study_engine.sample import FakeClock, load
from study_engine.stats import MIN_N_TO_CLAIM, summarize
from study_engine.store import Refused, Store, needs_confidence, parse_ts

ROOT = Path(__file__).resolve().parent.parent
D0 = date(2030, 1, 1)


def fresh():
    clock = FakeClock("2030-01-07T12:00:00")
    return Store(clock=clock, tz=timezone.utc, fuzz=False), clock


def count(store, table):
    return store.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


class ConfidenceRule(unittest.TestCase):
    def setUp(self):
        self.store, self.clock = fresh()
        self.card = self.store.add_card("D", "front", "back")

    def test_review_without_confidence_is_refused_and_stores_nothing(self):
        before = self.store.conn.execute("SELECT fsrs_state FROM cards").fetchone()[0]
        with self.assertRaisesRegex(Refused, "confidence missing"):
            self.store.review(self.card, 3)
        self.assertEqual(count(self.store, "reviews"), 0)
        self.assertEqual(self.store.conn.execute("SELECT fsrs_state FROM cards").fetchone()[0], before)

    def test_review_with_confidence_passes(self):
        self.assertEqual(self.store.review(self.card, 3, confidence=7)["confidence"], 7)

    def test_declared_reason_passes_and_is_stored(self):
        self.store.review(self.card, 3, no_confidence="a real exam, no rating possible")
        row = self.store.conn.execute("SELECT confidence, no_conf_reason FROM reviews").fetchone()
        self.assertIsNone(row["confidence"])
        self.assertIn("real exam", row["no_conf_reason"])

    def test_blank_reason_is_refused(self):
        for blank in ("", "   "):
            with self.assertRaisesRegex(Refused, "cannot be blank"):
                self.store.review(self.card, 3, no_confidence=blank)

    def test_confidence_bounds(self):
        for good in (0, 10):
            self.store.review(self.card, 3, confidence=good)
        for bad in (-1, 11):
            with self.assertRaisesRegex(Refused, "0 to 10"):
                self.store.review(self.card, 3, confidence=bad)

    def test_which_items_need_a_rating(self):
        self.assertTrue(needs_confidence("checkpoint", "2d"))
        self.assertTrue(needs_confidence("checkpoint", "3h"))
        self.assertTrue(needs_confidence("mock-1", "same-session"))
        self.assertFalse(needs_confidence("checkpoint", "same-session"))
        self.assertFalse(needs_confidence("quiz", "same-session"))
        self.assertFalse(needs_confidence("prequestion", "cold"))

    def test_delayed_attempt_without_rating_is_refused(self):
        with self.assertRaisesRegex(Refused, "confidence missing"):
            self.store.attempt("D", "checkpoint", "p", True, "2d")
        self.assertEqual(count(self.store, "attempts"), 0)
        self.store.attempt("D", "checkpoint", "p", True, "2d", confidence=4)
        self.assertEqual(count(self.store, "attempts"), 1)

    def test_same_session_attempt_needs_no_rating(self):
        self.store.attempt("D", "checkpoint", "p", True, "same-session")
        self.assertEqual(count(self.store, "attempts"), 1)


class RatingAndCorrectStayApart(unittest.TestCase):
    def setUp(self):
        self.store, self.clock = fresh()
        self.card = self.store.add_card("D", "front", "back")

    def test_generous_rating_does_not_inflate_accuracy(self):
        result = self.store.review(self.card, 3, confidence=5, correct=False)
        self.assertEqual(result["rating"], "Good")
        row = self.store.conn.execute("SELECT rating, correct FROM reviews").fetchone()
        self.assertEqual((row["rating"], row["correct"]), (3, 0))
        self.assertEqual(summarize(self.store)["accuracy"], 0.0)

    def test_doubt_words_lower_the_rating_only(self):
        self.store.review(self.card, 4, confidence=5, doubt="i guessed that one")
        row = self.store.conn.execute("SELECT rating, correct, doubt FROM reviews").fetchone()
        self.assertEqual((row["rating"], row["correct"]), (2, 1))
        self.assertEqual(row["doubt"], "i guessed that one")

    def test_doubt_never_raises(self):
        self.store.review(self.card, 1, confidence=5, doubt="not sure")
        self.assertEqual(self.store.conn.execute("SELECT rating FROM reviews").fetchone()[0], 1)

    def test_scheduling_uses_real_fsrs_and_good_pushes_out_further_than_again(self):
        other = self.store.add_card("D", "front 2", "back 2")
        first = self.store.review(self.card, 3, confidence=5)
        second = self.store.review(other, 1, confidence=5)
        self.assertGreater(first["stability_days"], second["stability_days"])
        self.assertGreater(parse_ts(first["next_due"]), self.clock())

    def test_due_after_review_moves_out(self):
        self.assertEqual(len(self.store.due("D")), 1)
        self.store.review(self.card, 4, confidence=9)
        self.assertEqual(len(self.store.due("D")), 0)
        self.clock.at += timedelta(days=60)
        self.assertEqual(len(self.store.due("D")), 1)


class SolidStatus(unittest.TestCase):
    """The arithmetic, pure. Boundary values of the gap are the planted cases."""

    def att(self, offset, correct=True, rung="base", delay="1d", shaky=False):
        return Attempt(D0 + timedelta(days=offset), correct, delay, rung, shaky)

    def test_new_type_is_due_the_day_after_since(self):
        status = solid_status([], D0)
        self.assertEqual((status.state, status.due), ("new", D0 + timedelta(days=1)))

    def test_same_session_attempts_do_not_count(self):
        self.assertEqual(solid_status([self.att(0, delay="same-session")], D0).state, "new")
        self.assertEqual(solid_status([self.att(0, delay="12h")], D0).state, "new")

    def test_first_solo_missed_comes_back_next_day(self):
        status = solid_status([self.att(3, correct=False)], D0)
        self.assertEqual((status.state, status.due), ("missed", D0 + timedelta(days=4)))

    def test_solid_needs_gap_and_variety(self):
        good = [self.att(0), self.att(6, rung="harder")]
        self.assertEqual(solid_status(good, D0).state, "solid")

    def test_gap_of_five_days_is_not_enough(self):
        status = solid_status([self.att(0), self.att(5, rung="harder")], D0)
        self.assertEqual(status.state, "building")
        self.assertEqual(status.due, D0 + timedelta(days=6))

    def test_same_rung_twice_is_not_solid(self):
        status = solid_status([self.att(0), self.att(10)], D0)
        self.assertEqual((status.state, status.need), ("building", "a different rung"))

    def test_two_non_base_rungs_count_as_varied(self):
        self.assertEqual(solid_status([self.att(0, rung="a"), self.att(6, rung="b")], D0).state, "solid")

    def test_same_non_base_rung_twice_is_not_varied(self):
        self.assertEqual(solid_status([self.att(0, rung="a"), self.att(6, rung="a")], D0).state, "building")

    def test_a_miss_resets_the_count(self):
        history = [self.att(0), self.att(6, rung="a"), self.att(7, correct=False), self.att(8)]
        self.assertEqual(solid_status(history, D0).state, "building")

    def test_solid_comes_back_for_maintenance(self):
        status = solid_status([self.att(0), self.att(6, rung="a")], D0)
        self.assertEqual(status.due, D0 + timedelta(days=6 + mastery.MAINTAIN_GAP_DAYS))

    def test_shaky_right_counts_as_neither(self):
        history = [self.att(0), self.att(6, rung="a", shaky=True)]
        self.assertEqual(solid_status(history, D0).state, "building")
        after_miss = [self.att(0, correct=False), self.att(1, shaky=True)]
        self.assertEqual(solid_status(after_miss, D0).state, "missed")

    def test_cold_boundary(self):
        self.assertFalse(mastery.is_cold("0.5d"))
        self.assertTrue(mastery.is_cold("1d"))
        self.assertFalse(mastery.is_cold("24h"))
        self.assertFalse(mastery.is_cold(None))

    def test_next_rung_waits_for_the_base(self):
        self.assertIsNone(mastery.next_rung([self.att(0, correct=False)], ["a", "b"]))
        self.assertEqual(mastery.next_rung([self.att(0)], ["a", "b"]), "a")

    def test_next_rung_prefers_never_tried_then_oldest(self):
        history = [self.att(0), self.att(1, rung="a"), self.att(2, correct=False, rung="b")]
        self.assertEqual(mastery.next_rung(history, ["a", "b", "c"]), "c")
        history.append(self.att(3, rung="c"))
        self.assertEqual(mastery.next_rung(history, ["a", "b", "c"]), "a")


class RungRule(unittest.TestCase):
    """A cold attempt on a type with a ladder has to say which rung it was."""

    def setUp(self):
        self.store, self.clock = fresh()
        self.ptype = self.store.add_ptype("D", "1.1", "kind", since="2030-01-01")
        self.store.add_rung(self.ptype, "plain", "the base", base=True)
        self.store.add_rung(self.ptype, "harder", "a harder version")

    def log(self, **kwargs):
        args = dict(source="cold-solo", prompt="p", correct=True, delay="2d", confidence=5, ptype=self.ptype)
        args.update(kwargs)
        return self.store.attempt("D", args.pop("source"), args.pop("prompt"), args.pop("correct"), args.pop("delay"), **args)

    def test_cold_attempt_with_no_rung_is_refused(self):
        with self.assertRaisesRegex(Refused, "must name its rung"):
            self.log()
        self.assertEqual(count(self.store, "attempts"), 0)

    def test_every_source_is_refused_alike(self):
        for source in ("cold-solo", "mock-1", "quiz", "checkpoint", "homework"):
            with self.assertRaisesRegex(Refused, "must name its rung"):
                self.log(source=source)

    def test_naming_the_rung_passes(self):
        self.log(rung="harder")
        self.assertEqual(count(self.store, "attempts"), 1)

    def test_unknown_rung_is_refused_with_the_valid_list(self):
        with self.assertRaisesRegex(Refused, "plain, harder"):
            self.log(rung="nope")

    def test_declared_reason_passes_and_counts_as_a_different_variant(self):
        self.log(rung="plain")
        self.clock.at += timedelta(days=7)
        self.log(no_rung="the question combined two rungs")
        self.assertEqual(self.store.status(self.ptype)["state"], "solid")

    def test_blank_reason_is_refused(self):
        with self.assertRaisesRegex(Refused, "cannot be blank"):
            self.log(no_rung="  ")

    def test_declaration_cannot_contradict_the_call(self):
        with self.assertRaisesRegex(Refused, "names one"):
            self.log(no_rung="none fits here", rung="harder")
        with self.assertRaisesRegex(Refused, "is for a cold attempt"):
            self.log(no_rung="none fits here", delay="same-session")
        bare = self.store.add_ptype("D", "1.2", "no ladder")
        with self.assertRaisesRegex(Refused, "no rungs yet"):
            self.log(no_rung="none fits here", ptype=bare)
        with self.assertRaisesRegex(Refused, "needs a problem type"):
            self.log(no_rung="none fits here", ptype=None)

    def test_left_alone_by_name(self):
        self.log(delay="same-session")
        self.log(delay="3h")
        self.log(ptype=None)
        bare = self.store.add_ptype("D", "1.2", "no ladder")
        self.log(ptype=bare)
        self.assertEqual(count(self.store, "attempts"), 4)

    def test_cold_prequestion_cannot_be_a_problem_type_attempt(self):
        with self.assertRaisesRegex(Refused, "real delay"):
            self.log(delay="cold")

    def test_bad_delay_is_refused(self):
        with self.assertRaisesRegex(Refused, "delay"):
            self.store.attempt("D", "quiz", "p", True, "tomorrow", confidence=1)

    def test_a_base_rung_scores_as_the_base(self):
        self.log(rung="plain")
        self.clock.at += timedelta(days=7)
        self.log(rung="plain")
        self.assertEqual(self.store.status(self.ptype)["state"], "building")

    def test_second_base_and_bad_key_are_refused(self):
        with self.assertRaisesRegex(Refused, "already has a base"):
            self.store.add_rung(self.ptype, "other", "another", base=True)
        with self.assertRaisesRegex(Refused, "lowercase slug"):
            self.store.add_rung(self.ptype, "Bad Key", "label")


class LadderShort(unittest.TestCase):
    def setUp(self):
        self.store, self.clock = fresh()
        self.ptype = self.store.add_ptype("D", "1.1", "kind", since="2030-01-01")
        self.store.add_rung(self.ptype, "plain", "the base", base=True)

    def solve_base(self):
        self.store.attempt("D", "cold-solo", "p", True, "2d", confidence=5, ptype=self.ptype, rung="plain")

    def test_fires_only_once_the_base_is_solved(self):
        self.assertFalse(self.store.status(self.ptype)["ladder_short"])
        self.solve_base()
        self.assertTrue(self.store.status(self.ptype)["ladder_short"])
        self.assertEqual(len(self.store.daily("D")["ladder_short"]), 1)

    def test_clears_once_the_rungs_are_written(self):
        self.solve_base()
        for index in range(4):
            self.store.add_rung(self.ptype, f"r{index}", "a rung")
        self.assertFalse(self.store.status(self.ptype)["ladder_short"])

    def test_declared_way_out(self):
        self.solve_base()
        self.store.declare_ladder_ok(self.ptype, "only two ways to ask this")
        self.assertFalse(self.store.status(self.ptype)["ladder_short"])

    def test_blank_declaration_is_refused(self):
        with self.assertRaisesRegex(Refused, "cannot be blank"):
            self.store.declare_ladder_ok(self.ptype, " ")

    def test_declaration_with_a_full_ladder_is_refused(self):
        for index in range(4):
            self.store.add_rung(self.ptype, f"r{index}", "a rung")
        with self.assertRaisesRegex(Refused, "nothing to excuse"):
            self.store.declare_ladder_ok(self.ptype, "only two ways to ask this")


class Daily(unittest.TestCase):
    def test_a_type_missed_on_its_first_solo_still_comes_back(self):
        store, clock = fresh()
        ptype = store.add_ptype("D", "1.1", "kind", since="2030-01-07")
        store.attempt("D", "cold-solo", "p", False, "1d", confidence=5, ptype=ptype)
        clock.at += timedelta(days=1)
        self.assertEqual([r["id"] for r in store.daily("D")["give"]], [ptype])

    def test_cap_limits_what_is_given(self):
        store, clock = fresh()
        for index in range(6):
            store.add_ptype("D", "1.1", f"kind {index}", since="2030-01-01")
        plan = store.daily("D")
        self.assertEqual(plan["cold_cap"], 3)
        self.assertEqual(len(plan["give"]), 3)

    def test_cold_attempts_today_count_against_the_cap(self):
        store, clock = fresh()
        ptypes = [store.add_ptype("D", "1.1", f"kind {i}", since="2030-01-01") for i in range(4)]
        store.attempt("D", "cold-solo", "p", True, "2d", confidence=5, ptype=ptypes[0])
        store.attempt("D", "cold-solo", "p", True, "2d", confidence=5, ptype=ptypes[1])
        self.assertEqual(len(store.daily("D")["give"]), 1)


class Stats(unittest.TestCase):
    def test_small_samples_say_so(self):
        store, _ = fresh()
        card = store.add_card("D", "f", "b")
        store.review(card, 3, confidence=5)
        self.assertIn("too few", summarize(store)["accuracy_verdict"])

    def test_the_bar_is_exact(self):
        store, _ = fresh()
        for index in range(MIN_N_TO_CLAIM - 1):
            store.attempt("D", "quiz", f"p{index}", True, "1d", confidence=5)
        self.assertIn("too few", summarize(store)["calibration"]["verdict"])
        store.attempt("D", "quiz", "last", True, "1d", confidence=5)
        self.assertEqual(summarize(store)["calibration"]["verdict"], "enough to read")

    def test_calibration_bias(self):
        store, _ = fresh()
        store.attempt("D", "quiz", "p1", False, "1d", confidence=10)
        store.attempt("D", "quiz", "p2", True, "1d", confidence=10)
        calibration = summarize(store)["calibration"]
        self.assertEqual(calibration["bias"], 0.5)
        self.assertEqual(calibration["bins"][3]["n"], 2)

    def test_coached_and_unassisted_are_never_pooled(self):
        store, _ = fresh()
        store.attempt("D", "quiz", "p1", True, "1d", confidence=5)
        store.attempt("D", "unassisted-week1", "p2", False, "1d", confidence=5)
        result = summarize(store)
        self.assertEqual(result["coached"], {"n": 1, "accuracy": 1.0})
        self.assertEqual(result["unassisted"], {"n": 1, "accuracy": 0.0})

    def test_weak_flags_misses_with_no_card(self):
        store, _ = fresh()
        miss = store.attempt("D", "quiz", "p", False, "1d", confidence=5, topic="rank")
        self.assertEqual(store.weak("D")[0]["no_card"], 1)
        store.add_card("D", "f", "b", from_attempt=miss)
        self.assertEqual(store.weak("D")[0]["no_card"], 0)


class Regressions(unittest.TestCase):
    def test_timestamp_with_trailing_z(self):
        self.assertEqual(parse_ts("2030-01-07T03:00:00Z"), datetime(2030, 1, 7, 3, tzinfo=timezone.utc))
        self.assertEqual(parse_ts("2030-01-07T03:00:00+00:00"), datetime(2030, 1, 7, 3, tzinfo=timezone.utc))


class Sample(unittest.TestCase):
    def test_sample_is_labeled_and_loads(self):
        data = json.loads((ROOT / "sample_data" / "sample_course.json").read_text())
        self.assertIn("SAMPLE DATA", data["_notice"])
        store, _, meta = load()
        states = {r["name"]: r["state"] for r in store.statuses(meta["deck"])}
        self.assertEqual(states["solve a 3 by 3 system by row reduction"], "solid")
        self.assertEqual(states["eigenvalues of a 2 by 2 matrix"], "missed")
        self.assertEqual(states["project a vector onto a line"], "new")


class CommandLine(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "study_engine", "--db", self.db, *args],
            cwd=ROOT, capture_output=True, text=True,
        )

    def test_refusal_exits_2_and_stores_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            self.db = str(Path(folder) / "t.db")
            self.assertEqual(self.run_cli("add", "--deck", "D", "--front", "f", "--back", "b").returncode, 0)
            refused = self.run_cli("review", "1", "--rating", "3")
            self.assertEqual(refused.returncode, 2)
            self.assertIn("REFUSED", refused.stderr)
            ok = self.run_cli("review", "1", "--rating", "3", "--confidence", "6")
            self.assertEqual(ok.returncode, 0, ok.stderr)
            self.assertEqual(json.loads(self.run_cli("stats").stdout)["scored_items"], 1)


if __name__ == "__main__":
    unittest.main()
