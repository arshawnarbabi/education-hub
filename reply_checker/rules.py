"""The rules a tutoring reply has to meet, as one flat list of checks.

Findings come in two groups:

    STOP    worth holding the reply for: the Stop hook sends it back once
    STYLE   reported to the coach but never holds a reply

Every STOP rule that can legitimately not apply has a declared way out: a line in
the reply such as "No picture: the student asked for words only". The declaration
needs a reason of at least two words. A blank one is itself a finding. A skipped
rule therefore always leaves a visible record.

Two classifiers keep the rules from firing where they do not apply, and both exist
because the first version got it wrong (docs/what-failed.md):

    explains()   a reply with enough worked math to count as an explanation
    asks_only()  all of its math sits in questions put to the student before they
                 answer, which must not be held for lacking a picture, since a
                 picture would give the answers away
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import curves, render, signs
from .text import DISPLAY, math_spans, strip_code, units, words

STOP_KINDS = ("render", "no-picture", "made-up-example", "reused-example")

DECLARE = {"no-picture": "no picture", "made-up-example": "made-up example"}
DECLARE_RE = "|".join(sorted(DECLARE.values(), key=len, reverse=True))

FIX = {
    "render": "rewrite the span so the chat renders it",
    "no-picture": "show a picture of this problem with the explanation, or declare: No picture: <reason>",
    "made-up-example": "use this problem's own lines and numbers, or declare: Made-up example: <reason>",
    "reused-example": "drop the made-up curve; it was already used once",
    "no-bold": "put the sentence that settles it in bold",
    "heading": "make the heading a question or a job (Find the radius is a label, Square the radius is a job)",
    "long-paragraph": "split it: at most 60 words or 3 sentences",
    "inline-equation": "move the long equation to its own display line",
    "yes-before-but": "do not open with an unqualified yes and then correct",
    "no-lead-in": "put plain words above the display line",
    "no-ask": "end on the student's turn",
    "no-sign-check": "say which sign changed, and ask the student to check it",
}

JOB_VERBS = {
    "find", "set", "square", "add", "check", "draw", "solve", "pick", "write", "compare", "try", "use", "plug",
    "factor", "expand", "simplify", "name", "start", "move", "reduce", "pivot", "swap",
}
EXAMPLE_WORDS = re.compile(
    r"\b(for example|for instance|e\.g\.|example:|say we have|suppose|imagine|let'?s say|a simpler one)\b", re.I
)
AFFIRM = re.compile(r"^\W*(yes|yep|yeah|exactly|correct|right|perfect|that'?s right)\W*$", re.I)
CORRECTION = re.compile(r"(^|\s)(but|however|not quite|careful|one fix|actually|except)\b", re.I)
ANSWER_MARKERS = re.compile(
    r"\b(?:because|since|so (?:the|its|it'?s|it|we|you|that|this)|which (?:gives|means|is why)|"
    r"that (?:gives|means|is why)|this (?:gives|means)|means that|therefore|thus|hence|we get|"
    r"you get|gives us|the answer is|answer:|that'?s why|plugging in|plug in)\b",
    re.I,
)
# A message about the tool itself is exempt from the teaching rules. Each word counts only next to a word that
# makes it about the tool: "solve the system of equations" and "a reducing agent" must not match.
ABOUT_THE_TOOL = re.compile(
    r"\b(?:the|this|that|a|new|stop)[- ]hooks?\b(?!\s+of\b)|"
    r"\b(?:the|this|that|new|background)[- ]agents?\b(?!\s+of\b)|"
    r"(?<!solve )(?<!solving )\bthe system\b(?!\s+of\b)|"
    r"\bthe (?:reply )?checker\b|\bclaude code\b",
    re.I,
)


@dataclass
class Context:
    """What the check knows besides the reply. Every field is optional."""

    prompt: str = ""                 # the student's message
    picture_shown: bool = False      # a picture tool ran this turn
    sources: str = ""                # the problem's own text
    earlier_made_up: set[str] = field(default_factory=set)  # made-up curves from earlier replies


@dataclass(frozen=True)
class Finding:
    kind: str
    detail: str

    @property
    def is_stop(self) -> bool:
        return self.kind in STOP_KINDS

    @property
    def fix(self) -> str:
        return FIX[self.kind]

    def __str__(self) -> str:
        return f"{self.kind}: {self.detail}. Fix: {self.fix}."


def declarations(text: str) -> dict[str, str]:
    """{kind: reason} for each declared way out. A blank reason is kept as ''."""
    out = {}
    for line in (text or "").split("\n"):
        match = re.match(r"^\s*[(*_]*\s*(" + DECLARE_RE + r")\s*[*_]*\s*:\s*(.*?)[)*_\s]*$", line, re.I)
        if match:
            kind = next(key for key, value in DECLARE.items() if value == match.group(1).lower())
            out[kind] = match.group(2).strip()
    return out


def _reason_ok(reason: str) -> bool:
    return len(re.findall(r"[A-Za-z]{2,}", reason or "")) >= 2


def body_of(text: str) -> str:
    return "\n".join(
        line
        for line in (text or "").split("\n")
        if not re.match(r"^\s*[(*_]*\s*(" + DECLARE_RE + r")\s*[*_]*\s*:", line, re.I)
    )


def explains(text: str) -> bool:
    """Enough worked math to count as an explanation. A yes, a one-line nudge or a question does not."""
    body = strip_code(body_of(text))
    spans = math_spans(body)
    display = sum(1 for is_display, _ in spans if is_display)
    inline_eqs = sum(1 for is_display, expr in spans if not is_display and "=" in expr)
    count = len(words(body))
    has_heading = re.search(r"^\s{0,3}#{1,6}\s+\S", body, re.M) is not None and bool(spans)
    return (
        display >= 2
        or (display >= 1 and count >= 50)
        or (inline_eqs >= 2 and count >= 50)
        or has_heading
        or (count >= 120 and bool(spans))
    )


def asks_only(text: str) -> bool:
    """All the reply's math sits in closed questions with nothing worked out."""
    body = strip_code(body_of(text))
    if not math_spans(body):
        return False
    asked = False
    for unit in units(body):
        spans = math_spans(unit)
        if not spans:
            continue
        plain = re.sub(r"\$\$.*?\$\$|\$[^$\n]*\$", " x ", unit, flags=re.S)
        ends_display = re.search(r"\$\$(.*?)\$\$\s*$", unit.strip(), re.S)
        ends_question = plain.rstrip(" \n*_)").endswith("?") or bool(
            ends_display and ends_display.group(1).strip().endswith("?")
        )
        worked = (
            ANSWER_MARKERS.search(plain) is not None
            or re.search(r"\\(?:Rightarrow|implies|Longrightarrow|therefore)\b", unit) is not None
            or re.search(r":\s*(?:\n|$|\$\$)", unit) is not None
            or sum(1 for is_display, _ in spans if is_display) > 1
        )
        if not ends_question or worked:
            return False
        asked = True
    return asked


def about_the_tool(prompt: str) -> bool:
    return ABOUT_THE_TOOL.search(prompt or "") is not None


def is_explanation(reply: str, context: Context) -> bool:
    return explains(reply) and not asks_only(reply) and not about_the_tool(context.prompt)


def example_curves(reply: str) -> list[str]:
    """Curves written in a paragraph that introduces an example, or on the display line right after it."""
    paragraphs = [p for p in re.split(r"\n\s*\n", strip_code(body_of(reply))) if p.strip()]
    found: list[str] = []
    for index, paragraph in enumerate(paragraphs):
        if EXAMPLE_WORDS.search(re.sub(r"\$[^$]*\$", " ", paragraph)):
            own = [curve.label for curve in curves.equations(paragraph)]
            found += own
            if not own and index + 1 < len(paragraphs) and paragraphs[index + 1].strip().startswith("$$"):
                found += [curve.label for curve in curves.equations(paragraphs[index + 1])]
    return found


def made_up_curves(reply: str, sources: str) -> list[str]:
    """With known sources, any foreign curve. Without them, only ones introduced with example words."""
    own = {curve.label for curve in curves.equations(sources or "", plain=True)}
    found = [label for label in example_curves(reply) if label not in own]
    found += [label for label in curves.foreign_curves(reply, sources) if label not in found]
    return found


def _stop_findings(reply: str, context: Context, explanation: bool, declared) -> list[Finding]:
    out = [Finding("render", f"{kind}: {snippet}") for kind, snippet in render.problems(reply)]
    if explanation and not context.picture_shown and not declared("no-picture"):
        out.append(Finding("no-picture", "an explanation with no picture shown this turn"))
    if not about_the_tool(context.prompt):
        made = [label for label in made_up_curves(reply, context.sources) if label not in context.earlier_made_up]
        if made and not declared("made-up-example"):
            out.append(Finding("made-up-example", "a curve not in this problem: " + ", ".join(made)))
        reused = sorted(
            {curve.label for curve in curves.equations(reply)} & set(context.earlier_made_up)
        )
        if reused:
            out.append(Finding("reused-example", ", ".join(reused)))
    return out


def _style_findings(reply: str, explanation: bool) -> list[Finding]:
    body = strip_code(body_of(reply))
    out: list[Finding] = []

    for heading in re.findall(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", body, re.M):
        tokens = re.sub(r"\$[^$]*\$", " x ", heading).split() or [""]
        first = re.sub(r"[^a-z']", "", tokens[0].lower())
        if not heading.rstrip().endswith("?") and first not in JOB_VERBS:
            out.append(Finding("heading", heading[:80]))

    first_paragraph = re.split(r"\n\s*\n", body.strip(), maxsplit=1)[0]
    pieces = re.split(r"(?<=[.?])\s+|\n", first_paragraph, maxsplit=1)
    if len(pieces) > 1 and AFFIRM.match(pieces[0]) and CORRECTION.search(" " + pieces[1]):
        out.append(Finding("yes-before-but", pieces[0][:30]))

    moves = signs.reply_sign_moves(reply)
    if moves and not signs.mentions_signs(body):
        out.append(Finding("no-sign-check", moves[0]))

    if not explanation:
        return out

    if not re.search(r"\*\*[^*\n]{3,}\*\*", body):
        out.append(Finding("no-bold", "no bold sentence"))

    for paragraph in re.split(r"\n\s*\n", DISPLAY.sub("\n\n", body)):
        lines = [
            line for line in paragraph.strip().split("\n") if not re.match(r"^\s*([-*+|>#]|\d+[.)])\s", line)
        ]
        prose = "\n".join(lines).strip()
        if not prose:
            continue
        sentences = [s for s in re.split(r"(?<=[.?])\s+", re.sub(r"\$[^$]*\$", "x", prose)) if words(s)]
        if len(words(prose)) > 60 or len(sentences) > 3:
            out.append(Finding("long-paragraph", prose[:60] + "..."))

    for line in DISPLAY.sub(" ", body).split("\n"):
        for expr in re.findall(r"(?<![\\$])\$(?!\$)([^$\n]+?)\$(?!\$)", line):
            if len(words(line)) > 4 and _display_worthy(expr):
                out.append(Finding("inline-equation", "$" + expr.strip()[:60] + "$"))

    blocks = [block.strip() for block in re.split(r"\n\s*\n", body) if block.strip()]
    for index, block in enumerate(blocks):
        if block.startswith("$$") and not re.match(r"\$\$\s*(=|\\implies|\\Rightarrow|&)", block):
            above = blocks[index - 1] if index else ""
            if not above or above.startswith("$$") or above.startswith("#"):
                out.append(Finding("no-lead-in", block[:60]))

    if body.strip() and not body.strip().rstrip("*_ ").endswith("?"):
        out.append(Finding("no-ask", "the reply does not end on a question"))
    return out


def _display_worthy(expr: str) -> bool:
    relations = len(re.findall(r"(?<![<>\\])=", expr))
    if relations == 0:
        return False
    if relations >= 2:
        return True
    return len(re.sub(r"\\[A-Za-z]+|\\[,;:  ]|[{}\s]", "", expr)) > 12


def check(reply: str, context: Context | None = None) -> list[Finding]:
    """Every finding in one reply. This is the whole public interface of the rule set."""
    context = context or Context()
    decl = declarations(reply)
    blanks: list[Finding] = []

    def declared(kind: str) -> bool:
        if kind not in decl:
            return False
        if not _reason_ok(decl[kind]):
            blanks.append(Finding(kind, f'"{DECLARE[kind].capitalize()}:" has a blank reason'))
        return True

    explanation = is_explanation(reply, context)
    return _stop_findings(reply, context, explanation, declared) + blanks + _style_findings(reply, explanation)
