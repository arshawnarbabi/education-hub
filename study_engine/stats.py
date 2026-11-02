"""Summary numbers, with a bar for when they may be read as more than noise."""
from __future__ import annotations

from .store import Store

MIN_N_TO_CLAIM = 20   # under this, the report says so instead of stating a rate
BINS = ((0, 3, "0-3"), (4, 6, "4-6"), (7, 8, "7-8"), (9, 10, "9-10"))


def _rate(values: list[int]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


def _verdict(n: int) -> str:
    return "enough to read" if n >= MIN_N_TO_CLAIM else f"too few to claim anything (n={n}, bar is {MIN_N_TO_CLAIM})"


def summarize(store: Store, deck: str | None = None) -> dict:
    """Accuracy, confidence calibration and coached against unassisted work.

    Calibration compares mean confidence to accuracy over items that carry a
    rating. Bias above zero is overconfidence. Unassisted is any item whose
    source starts with 'unassisted', so work done with help is never pooled with
    work done alone.
    """
    rows = store._scored(deck)
    correct = [row["correct"] for row in rows]
    rated = [row for row in rows if row["confidence"] is not None]

    calibration = None
    if rated:
        mean_conf = sum(row["confidence"] for row in rated) / (10 * len(rated))
        accuracy = sum(row["correct"] for row in rated) / len(rated)
        calibration = {
            "n": len(rated),
            "mean_confidence": round(mean_conf, 3),
            "accuracy": round(accuracy, 3),
            "bias": round(mean_conf - accuracy, 3),
            "verdict": _verdict(len(rated)),
            "bins": [
                {
                    "confidence": label,
                    "n": len(items),
                    "accuracy": _rate([row["correct"] for row in items]),
                }
                for low, high, label in BINS
                for items in [[row for row in rated if low <= row["confidence"] <= high]]
            ],
        }

    alone = [row["correct"] for row in rows if row["source"].startswith("unassisted")]
    coached = [row["correct"] for row in rows if not row["source"].startswith("unassisted")]
    return {
        "scored_items": len(rows),
        "accuracy": _rate(correct),
        "accuracy_verdict": _verdict(len(rows)),
        "unrated": len(rows) - len(rated),
        "calibration": calibration,
        "coached": {"n": len(coached), "accuracy": _rate(coached)},
        "unassisted": {"n": len(alone), "accuracy": _rate(alone)},
    }
