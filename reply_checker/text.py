"""Reading a markdown reply: code, math spans and plain words. No policy lives here."""
from __future__ import annotations

import re

FENCE = re.compile(r"```.*?```", re.S)
CODE = re.compile(r"`[^`\n]*`")
DISPLAY = re.compile(r"\$\$(.*?)\$\$", re.S)
INLINE = re.compile(r"(?<![\\$])\$(?!\$)([^$\n]+?)\$(?!\$)")


def strip_code(text: str) -> str:
    return CODE.sub(" ", FENCE.sub(" ", text or ""))


def math_spans(text: str) -> list[tuple[bool, str]]:
    """(is_display, expression) for every math span outside code."""
    plain = strip_code(text)
    spans = [(True, match.group(1)) for match in DISPLAY.finditer(plain)]
    spans += [(False, match.group(1)) for match in INLINE.finditer(DISPLAY.sub(" ", plain))]
    return spans


def words(text: str) -> list[str]:
    """Plain words: math and markup left out."""
    plain = INLINE.sub(" ", DISPLAY.sub(" ", text))
    plain = re.sub(r"[*_#>|`]", " ", plain)
    return [word for word in plain.split() if re.search(r"[A-Za-z]", word)]


def without_math(text: str) -> str:
    return INLINE.sub(" ", DISPLAY.sub(" ", text))


def units(body: str) -> list[str]:
    """Paragraphs, with each list item its own unit."""
    item = re.compile(r"^\s{0,3}(?:\d+[.)]|[-*+])\s+")
    out: list[str] = []
    for paragraph in re.split(r"\n\s*\n", body):
        current: list[str] = []
        for line in paragraph.split("\n"):
            if item.match(line) and current:
                out.append("\n".join(current))
                current = []
            current.append(line)
        if current:
            out.append("\n".join(current))
    return [unit for unit in out if unit.strip()]
