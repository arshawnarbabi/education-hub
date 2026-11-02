"""The Claude Code Stop hook: hold a reply once when a STOP rule fails.

Claude Code runs this when the assistant finishes a turn, with JSON on stdin.
Printing {"decision": "block", "reason": ...} sends the reason back to the model
and the turn continues, so it fixes the reply before the person moves on.

Three properties matter more than the rules themselves:

* It holds once. On the stop after a hold, Claude Code sets stop_hook_active and
  the hook stays silent, so a rule that cannot be met can never trap a session.
* It fails open. Any crash allows the stop and writes to a log file. A broken
  checker must not break the session, and its errors must not vanish either.
* It reads, it does not trust. The check runs on the transcript, not on what the
  model says it did.

Settings: see examples/settings.stop-hook.json.
Environment, all optional:
    REPLY_CHECK_SOURCES   a file with the current problem's text
    REPLY_CHECK_LOG       where crashes go (default: reply_check_errors.log beside the transcript)
    REPLY_CHECK_PICTURES  regular expression for tool names that show a picture
"""
from __future__ import annotations

import json
import os
import re
import sys
import traceback

from .rules import Context, check, made_up_curves
from .transcript import Turn, read_entries, turns

DEFAULT_PICTURE_TOOLS = r"show_widget|show_image|render_figure"


def _sources(all_turns: list[Turn]) -> str:
    """The problem's own text: everything the student wrote, plus a file if one is configured."""
    parts = [turn.prompt for turn in all_turns]
    path = os.environ.get("REPLY_CHECK_SOURCES")
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            parts.append(handle.read())
    return "\n".join(parts)


def build_context(all_turns: list[Turn]) -> Context:
    last = all_turns[-1]
    sources = _sources(all_turns)
    pictures = re.compile(os.environ.get("REPLY_CHECK_PICTURES", DEFAULT_PICTURE_TOOLS))
    earlier: set[str] = set()
    for turn in all_turns[:-1]:
        earlier.update(made_up_curves(turn.reply, sources))
    return Context(
        prompt=last.prompt,
        picture_shown=any(pictures.search(tool) for tool in last.tools),
        sources=sources,
        earlier_made_up=earlier,
    )


def decide(stdin_text: str) -> str:
    """The JSON to print, or an empty string to allow the stop."""
    try:
        data = json.loads(stdin_text or "{}")
    except ValueError:
        return ""
    if data.get("stop_hook_active"):
        return ""
    all_turns = turns(read_entries(data.get("transcript_path") or ""))
    if not all_turns or not all_turns[-1].reply:
        return ""
    held = [finding for finding in check(all_turns[-1].reply, build_context(all_turns)) if finding.is_stop]
    if not held:
        return ""
    reason = "Reply check. Fix each of these now, with a short correction of only that part:\n" + "\n".join(
        f"- {finding}" for finding in held
    )
    return json.dumps({"decision": "block", "reason": reason})


def _log_crash(stdin_text: str) -> None:
    try:
        transcript = json.loads(stdin_text or "{}").get("transcript_path") or ""
    except ValueError:
        transcript = ""
    default = os.path.join(os.path.dirname(transcript) or ".", "reply_check_errors.log")
    with open(os.environ.get("REPLY_CHECK_LOG", default), "a", encoding="utf-8") as handle:
        handle.write(traceback.format_exc() + "\n")


def main() -> int:
    stdin_text = sys.stdin.read()
    try:
        output = decide(stdin_text)
    except Exception:  # fail open, but never silently
        _log_crash(stdin_text)
        return 0
    if output:
        print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
