"""Load the made-up sample course into a store. See sample_data/README.md."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .store import Store

SAMPLE = Path(__file__).resolve().parent.parent / "sample_data" / "sample_course.json"


class FakeClock:
    """A settable clock, so sample data and tests never depend on the real date."""

    def __init__(self, start: str):
        self.at = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.at

    def set_day(self, offset_days: int, start: datetime) -> None:
        self.at = start + timedelta(days=offset_days)


def load(path: str = ":memory:") -> tuple[Store, FakeClock, dict]:
    """A store holding the sample course's cards, types and history, with its clock at the course's last day."""
    data = json.loads(SAMPLE.read_text())
    start = datetime.fromisoformat(data["start"]).replace(tzinfo=timezone.utc)
    clock = FakeClock(data["start"])
    store = Store(path, clock=clock, tz=timezone.utc, fuzz=False)
    deck = data["deck"]

    cards = [store.add_card(deck, c["front"], c["back"], source="sample") for c in data["cards"]]
    ptypes = {}
    for item in data["problem_types"]:
        ptype = store.add_ptype(deck, item["section"], item["name"], since=item["since"])
        ptypes[item["name"]] = ptype
        for rung in item["rungs"]:
            store.add_rung(ptype, rung["key"], rung["label"], base=rung.get("base", False))

    events = sorted(data["history"], key=lambda e: e["day"])
    for event in events:
        clock.set_day(event["day"], start)
        if event["kind"] == "review":
            store.review(
                cards[event["card"]], event["rating"], confidence=event["confidence"], correct=event["correct"]
            )
        else:
            store.attempt(
                deck, event["source"], event["prompt"], event["correct"], event["delay"],
                confidence=event.get("confidence"), topic=event.get("topic"),
                ptype=ptypes.get(event.get("ptype")), rung=event.get("rung"),
            )
    clock.set_day(data["last_day"], start)
    return store, clock, {"deck": deck, "cards": cards, "ptypes": ptypes, "start": start}
