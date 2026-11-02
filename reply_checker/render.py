"""Math that a chat front end shows as raw text instead of rendering.

Each entry is a bug that was seen in a real chat client and then reproduced. The
list is specific to that client's parser, so treat it as a template for your own
renderer, not as a statement about LaTeX. Display math, code and ordinary money
("$29.68") are left alone on purpose.
"""
from __future__ import annotations

import re

from .text import DISPLAY, strip_code

_SPAN = re.compile(r"(?<![\\$])\$(?!\$)(\S(?:[^$\n]*?\S)?)\$(?!\$)")
_MONEY = re.compile(r"^\d[\d,]*(\.\d+)?$")
_WORD = re.compile(r"^[A-Za-z]{2,}$")
_MATH_START = re.compile(r"\$(?=\\[A-Za-z]|[A-Za-z][\s=^_+\-*/)])")


def _balanced(expr: str) -> bool:
    depth = 0
    for index, char in enumerate(expr):
        if index and expr[index - 1] == "\\":
            continue
        depth += {"{": 1, "}": -1}.get(char, 0)
        if depth < 0:
            return False
    return depth == 0


def problems(text: str) -> list[tuple[str, str]]:
    """Every render bug as (kind, snippet)."""
    plain = strip_code(text)
    found: list[tuple[str, str]] = []

    for match in DISPLAY.finditer(plain):
        expr = match.group(1)
        if "\\bbox" in expr:
            found.append(("bbox", expr[:40].strip()))
        if not _balanced(expr):
            found.append(("unbalanced-braces", expr[:40].strip()))

    inline_text = DISPLAY.sub(" ", plain)
    for line in inline_text.split("\n"):
        for match in _SPAN.finditer(line):
            expr = match.group(1)
            if _MONEY.match(expr):
                found.append(("bare-number", match.group(0)))
            elif _WORD.match(expr):
                found.append(("word-span", match.group(0)))
            elif re.search(r"\\(?:text)?color\s*\{", expr):
                found.append(("inline-color", match.group(0)[:40]))
            if line[match.end() : match.end() + 1].isdigit():
                found.append(("digit-close", match.group(0)))
        leftover = _SPAN.sub(" ", line)
        if re.search(r"(?<![\\$])\$ \S[^$]*\$", leftover):
            found.append(("space-open", leftover.strip()[:40]))
        elif _MATH_START.search(leftover) and leftover.count("$") == 1:
            found.append(("unclosed", leftover.strip()[:40]))
    return found
