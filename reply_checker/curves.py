"""Is this curve the problem's own? Compared by value, not by text.

Rewriting is legitimate while teaching: x = 21 - y is the same curve as y = 21 - x.
So the check reads each right-hand side into a safe expression and tests sample
points of one curve against the other. A curve that matches nothing in the
problem's text is a made-up example.

A right-hand side is parsed by hand and then checked again with the ast module.
Only numbers, x, y, e, pi, arithmetic and a short list of functions can reach
eval, which runs with no builtins.
"""
from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass

from .text import DISPLAY, INLINE, math_spans, strip_code

CURVE_LHS = re.compile(r"^\s*(?:y|x|[fgh]\s*\(\s*[xy]\s*\))\s*=\s*(.+?)\s*$")
_FUNCS = {"sin", "cos", "tan", "sqrt", "ln", "log", "exp", "arctan", "pi"}
_NS = {
    "__builtins__": {},
    "sin": math.sin, "cos": math.cos, "tan": math.tan, "sqrt": math.sqrt, "ln": math.log,
    "log": math.log, "exp": math.exp, "arctan": math.atan, "pi": math.pi, "e": math.e,
}
_SAMPLES = (-3.7, -1.3, 0.37, 0.61, 1.9, 2.8, 4.4, 7.3)
_ATOM = re.compile(r"\d+(?:\.\d+)?|[xye]|pi")
_ALLOWED_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.USub, ast.UAdd,
    ast.Call, ast.Name, ast.Load, ast.Constant,
)


@dataclass(frozen=True)
class Curve:
    var: str      # the variable it solves for
    python: str   # the right-hand side, safe to evaluate
    label: str    # the right-hand side, normalized, for messages and text matches


def normalize(expr: str) -> str:
    cleaned = re.sub(r"\\left|\\right|\\,|\\!|\\;|\\:|\\ |\s+", "", expr or "")
    return cleaned.replace("{", "").replace("}", "").lower()


def _group(text: str, start: int) -> tuple[str, int] | None:
    """(content, end) of the {...} group opening at text[start], or None."""
    if start >= len(text) or text[start] != "{":
        return None
    depth = 0
    for index in range(start, len(text)):
        depth += {"{": 1, "}": -1}.get(text[index], 0)
        if depth == 0:
            return text[start + 1 : index], index + 1
    return None


def to_python(expr: str) -> str | None:
    """A LaTeX or plain right-hand side as Python in x and y, or None if it holds anything else."""
    text = (expr or "").strip().rstrip(".,;:")
    text = re.sub(r"\\(?:text)?color\{[^{}]*\}", "", text)
    text = re.sub(r"\\left|\\right|\\displaystyle|\\[,;:! ]", "", text)
    text = text.replace("\\cdot", "*").replace("\\times", "*")
    for _ in range(20):
        match = re.search(r"\\[dt]?frac\s*(?=\{)|\\sqrt\s*(?=\{)", text)
        if not match:
            break
        first = _group(text, match.end())
        if not first:
            return None
        if "frac" in match.group(0):
            second = _group(text, first[1])
            if not second:
                return None
            text = f"{text[:match.start()]}(({first[0]})/({second[0]})){text[second[1]:]}"
        else:
            text = f"{text[:match.start()]}sqrt({first[0]}){text[first[1]:]}"
    text = re.sub(r"\\(" + "|".join(sorted(_FUNCS, key=len, reverse=True)) + r")(?![A-Za-z])", r" \1 ", text)
    if "\\" in text or re.search(r"[^0-9A-Za-z.+\-*/^(){}\s]", text):
        return None
    text = text.replace("{", "(").replace("}", ")").replace("^", "**")
    tokens = re.findall(r"\d+(?:\.\d+)?|[A-Za-z]+|\*\*|[-+*/()]", text)
    if "".join(tokens) != re.sub(r"\s+", "", text):
        return None

    expanded: list[str] = []
    for token in tokens:
        if token.isalpha() and token not in _FUNCS:
            if not set(token) <= {"x", "y", "e"}:
                return None
            expanded += list(token)
        else:
            expanded.append(token)

    output: list[str] = []
    index = 0
    while index < len(expanded):
        token = expanded[index]
        previous = output[-1] if output else None
        previous_is_atom = previous is not None and (_ATOM.fullmatch(previous) is not None or previous == ")")
        token_starts_atom = _ATOM.fullmatch(token) is not None or token == "(" or token in _FUNCS
        if previous_is_atom and token_starts_atom:
            output.append("*")  # implicit multiplication: 2x, 3(y + 1)
        if token in _FUNCS and token != "pi" and index + 1 < len(expanded) and expanded[index + 1] != "(":
            argument = expanded[index + 1]
            if not _ATOM.fullmatch(argument):
                return None
            output += [token, "(", argument, ")"]
            index += 2
            continue
        output.append(token)
        index += 1
    python = "".join(output)
    return python if _is_safe(python) else None


def _is_safe(python: str) -> bool:
    try:
        tree = ast.parse(python, mode="eval")
    except (SyntaxError, ValueError):
        return False
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            return False
        if isinstance(node, ast.Name) and node.id not in _NS and node.id not in ("x", "y"):
            return False
        if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float)):
            return False
    return True


def equations(text: str, plain: bool = False) -> list[Curve]:
    """The curves a text writes. plain=True also reads unmarked ones, as a student types them."""
    pieces: list[str] = []
    for _, expr in math_spans(text or ""):
        pieces += re.split(r"\\quad|\\qquad|,|\\text\{[^}]*\}|\\\\|\\Rightarrow|\\implies|\\to", expr)
    if plain:
        bare = INLINE.sub(" ", DISPLAY.sub(" ", strip_code(text or "")))
        pieces += [
            match.group(0)
            for match in re.finditer(
                r"(?<![A-Za-z])(?:[yx]|f\([xy]\))\s*=\s*[^\s,;?]+(?:\s*[-+]\s*[^\s,;?]+)*", bare
            )
        ]
    found = []
    for part in pieces:
        match = CURVE_LHS.match(part)
        if not match:
            continue
        lhs = re.sub(r"\s", "", part.split("=")[0])
        var = "y" if lhs == "y" or lhs.endswith("(x)") else "x"
        python = to_python(match.group(1))
        if not python:
            continue
        names = {node.id for node in ast.walk(ast.parse(python, mode="eval")) if isinstance(node, ast.Name)}
        if {"x", "y"} & names and var not in names:
            found.append(Curve(var, python, normalize(match.group(1))))
    return found


def same_curve(first: Curve, second: Curve) -> bool:
    """Sample points of one lie on the other, in either direction."""

    def values(curve: Curve, x: float, y: float) -> float:
        return eval(compile(curve.python, "<curve>", "eval"), dict(_NS, x=x, y=y))  # checked by _is_safe

    def onto(p: Curve, q: Curve) -> bool:
        good = 0
        for t in _SAMPLES:
            try:
                x, y = (t, values(p, t, 0.0)) if p.var == "y" else (values(p, 0.0, t), t)
                other = values(q, x, y)
                if isinstance(x, complex) or isinstance(y, complex) or isinstance(other, complex):
                    continue
                target = y if q.var == "y" else x
                if abs(other - target) > 1e-6 * max(1.0, abs(x), abs(y)):
                    return False
                good += 1
            except (ValueError, ZeroDivisionError, OverflowError, TypeError):
                continue
        return good >= 2

    try:
        return onto(first, second) or onto(second, first)
    except Exception:  # one odd curve is left alone, never fatal
        return False


def foreign_curves(reply: str, sources: str) -> list[str]:
    """Curves the reply writes that are not the problem's own. Empty when the problem's curves are unknown."""
    own = equations(sources or "", plain=True)
    if not own:
        return []
    labels = {curve.label for curve in own}
    return [
        curve.label
        for curve in equations(reply)
        if curve.label not in labels and not any(same_curve(curve, source) for source in own)
    ]
