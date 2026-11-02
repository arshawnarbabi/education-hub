"""Read a Claude Code session transcript (JSON lines) into turns.

Only what the rules need: each user prompt, the assistant text after it and the
tools used. A malformed line is skipped, never fatal, because this runs inside a
hook and a crash there must not take a session down.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

TAIL_BYTES = 4_000_000
_NOT_A_PROMPT = ("<local-command", "<command-name>", "<task-notification>")


@dataclass
class Turn:
    prompt: str
    text: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)

    @property
    def reply(self) -> str:
        return "\n\n".join(self.text)


def read_entries(path: str, max_bytes: int = TAIL_BYTES) -> list[dict]:
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as handle:
            if size > max_bytes:
                handle.seek(size - max_bytes)
                handle.readline()  # drop the partial first line
            raw = handle.read().decode("utf-8", "replace")
    except OSError:
        return []
    entries = []
    for line in raw.splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict):
            entries.append(entry)
    return entries


def _prompt_text(entry: dict) -> str | None:
    """The text if this entry is a real prompt: not a tool result, a meta line or a command echo."""
    if entry.get("type") != "user" or entry.get("isMeta") or entry.get("isSidechain"):
        return None
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        if any(isinstance(block, dict) and block.get("type") == "tool_result" for block in content):
            return None
        text = "\n".join(
            block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text"
        )
    else:
        return None
    stripped = text.strip()
    return None if not stripped or stripped.startswith(_NOT_A_PROMPT) else text


def turns(entries: list[dict]) -> list[Turn]:
    out: list[Turn] = []
    for entry in entries:
        prompt = _prompt_text(entry)
        if prompt is not None:
            out.append(Turn(prompt))
        elif out and entry.get("type") == "assistant" and not entry.get("isSidechain"):
            for block in (entry.get("message") or {}).get("content") or []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    out[-1].text.append(block.get("text", ""))
                elif block.get("type") == "tool_use":
                    out[-1].tools.append(block.get("name", ""))
    return out
