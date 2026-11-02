"""Detect a sign move between two consecutive equations.

A sign move is a term that crosses the equals sign, or a minus distributed into a
bracket. Those are the steps where a dropped sign is easiest to miss, so the rule
asks that the reply says so. Detection is on two equations in a row: every term
of the first shows up in the second, and one of them now has the opposite sign.
"""
from __future__ import annotations

import re

from .text import math_spans, strip_code


def _clean(expr: str) -> str:
    return re.sub(r"\\left|\\right|\\,|\\;|\\:|\\!|\\ |\s+", "", expr or "")


def sides(expr: str) -> tuple[str, str] | None:
    """The two sides of an equation with exactly one top-level '=', else None."""
    text = _clean(expr)
    depth = 0
    cuts = []
    for index, char in enumerate(text):
        if char in "({[":
            depth += 1
        elif char in ")}]":
            depth -= 1
        elif char == "=" and depth == 0 and (index == 0 or text[index - 1] not in "<>!\\"):
            cuts.append(index)
    if len(cuts) != 1:
        return None
    left, right = text[: cuts[0]], text[cuts[0] + 1 :]
    return (left, right) if left and right else None


def terms(side: str) -> list[tuple[str, str]]:
    """[(sign, term)] at the top level: 'y+7' gives [('+', 'y'), ('+', '7')]."""
    out: list[tuple[str, str]] = []
    buffer, sign, depth = "", "+", 0
    for char in side:
        if char in "({[":
            depth += 1
        elif char in ")}]":
            depth -= 1
        if char in "+-" and depth == 0 and (not buffer or buffer[-1] not in "^_*/"):
            if buffer:
                out.append((sign, buffer))
                buffer, sign = "", char
            else:
                sign = "-" if (sign == "-") != (char == "-") else "+"
            continue
        buffer += char
    if buffer:
        out.append((sign, buffer))
    return out


def _core(term: str) -> str:
    """A term without its leading number: '3x' gives 'x'. A bare number stays itself."""
    return re.sub(r"^\d+(\.\d+)?", "", term) or term


def _present(core: str, text: str) -> bool:
    if re.fullmatch(r"\d+(\.\d+)?", core):
        return re.search(r"(?<![\d.])" + re.escape(core) + r"(?![\d.])", text) is not None
    return core in text


def sign_moves(first: str, second: str) -> list[str]:
    """The sign moves from one equation to the next. Empty: none, or not the same equation."""
    sides_a, sides_b = sides(first), sides(second)
    if not sides_a or not sides_b:
        return []
    raw_b = _clean(second)
    signed_b = "=".join("".join(sign + term for sign, term in terms(side)) for side in sides_b)
    terms_a = [item for side in sides_a for item in terms(side)]
    atoms = [
        atom
        for _, term in terms_a
        for _, atom in (terms(term[1:-1]) if re.fullmatch(r"\(.*\)", term) else [("+", term)])
    ]
    if not terms_a or not all(_present(_core(atom), raw_b) for atom in atoms):
        return []
    moves = []
    for sign, term in terms_a:
        flipped = "-" if sign == "+" else "+"
        flipped_there = flipped + term in signed_b + "|" + raw_b
        own_there = sign + term in signed_b
        bare_positive = sign == "+" and re.search(r"(^|[=({])" + re.escape(term) + r"($|[-+=)}])", raw_b)
        if flipped_there and not own_there and not bare_positive:
            moves.append(f"{sign}{term} became {flipped}{term}")
    for match in re.finditer(r"-\(([^()]+)\)", _clean(first)):
        group = match.group(1)
        if "-(" + group + ")" not in raw_b and all(_present(_core(t), raw_b) for _, t in terms(group)):
            moves.append(f"the minus in front of ({group}) was distributed")
    return moves


def display_equations(text: str) -> list[str]:
    found = []
    for is_display, expr in math_spans(text):
        if is_display:
            found += [part for part in re.split(r"\\\\|\\quad|\\qquad", expr) if sides(part)]
    return found


def reply_sign_moves(reply: str) -> list[str]:
    equations = display_equations(reply)
    return [move for a, b in zip(equations, equations[1:]) for move in sign_moves(a, b)]


def mentions_signs(text: str) -> bool:
    plain = re.sub(r"\$\$.*?\$\$", " ", strip_code(text), flags=re.S)
    return "sign" in plain.lower()
