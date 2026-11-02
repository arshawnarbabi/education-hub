"""The Stop hook, run as Claude Code runs it: a subprocess with JSON on stdin and a transcript file."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

BAD = "Suppose $y = 2x$ instead, so the answer is $5$."
GOOD = "Now look at the line you gave.\n\n**It is $y = 3x + 1$.** What is its slope?"


def entry_user(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def entry_assistant(text, *tools):
    content = [{"type": "text", "text": text}] + [{"type": "tool_use", "name": tool, "input": {}} for tool in tools]
    return {"type": "assistant", "message": {"role": "assistant", "content": content}}


class StopHook(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "session.jsonl"

    def write(self, *entries, junk=False):
        lines = [json.dumps(entry) for entry in entries]
        if junk:
            lines.insert(1, "{not json")
        self.path.write_text("\n".join(lines) + "\n")

    def run_hook(self, stdin=None, env=None, **extra):
        payload = {"transcript_path": str(self.path), **extra}
        return subprocess.run(
            [sys.executable, "-m", "reply_checker.stop_hook"],
            cwd=ROOT,
            input=json.dumps(payload) if stdin is None else stdin,
            capture_output=True,
            text=True,
            env={**os.environ, **(env or {})},
        )

    def test_a_bad_reply_is_held_with_a_reason(self):
        self.write(entry_user("the line is y = 3x + 1"), entry_assistant(BAD))
        done = self.run_hook()
        self.assertEqual(done.returncode, 0)
        decision = json.loads(done.stdout)
        self.assertEqual(decision["decision"], "block")
        self.assertIn("made-up-example", decision["reason"])
        self.assertIn("render", decision["reason"])

    def test_the_compliant_twin_is_allowed(self):
        self.write(entry_user("the line is y = 3x + 1"), entry_assistant(GOOD))
        done = self.run_hook()
        self.assertEqual((done.returncode, done.stdout), (0, ""))

    def test_holds_once_only(self):
        self.write(entry_user("the line is y = 3x + 1"), entry_assistant(BAD))
        self.assertEqual(self.run_hook(stop_hook_active=True).stdout, "")

    def test_a_picture_tool_in_the_transcript_counts(self):
        explanation = "First.\n\n$$y = 1$$\n\nThen.\n\n$$x = 2$$\n\n**Done.** Next?"
        self.write(entry_user("go"), entry_assistant(explanation))
        self.assertIn("no-picture", self.run_hook().stdout)
        self.write(entry_user("go"), entry_assistant(explanation, "show_widget"))
        self.assertEqual(self.run_hook().stdout, "")

    def test_a_picture_tool_in_an_earlier_turn_does_not_count(self):
        explanation = "First.\n\n$$y = 1$$\n\nThen.\n\n$$x = 2$$\n\n**Done.** Next?"
        self.write(
            entry_user("one"), entry_assistant("ok", "show_widget"), entry_user("two"), entry_assistant(explanation)
        )
        self.assertIn("no-picture", self.run_hook().stdout)

    def test_picture_tools_are_configurable(self):
        explanation = "First.\n\n$$y = 1$$\n\nThen.\n\n$$x = 2$$\n\n**Done.** Next?"
        self.write(entry_user("go"), entry_assistant(explanation, "my_plot"))
        self.assertEqual(self.run_hook(env={"REPLY_CHECK_PICTURES": "my_plot"}).stdout, "")

    def test_earlier_made_up_curve_is_reused_example(self):
        self.write(
            entry_user("the line is y = 3x + 1"),
            entry_assistant("Now look at $y = 2x$."),
            entry_user("ok"),
            entry_assistant("Back to $y = 2x$."),
        )
        self.assertIn("reused-example", self.run_hook().stdout)

    def test_sources_file_supplies_the_problems_curves(self):
        problem = Path(self.folder.name) / "problem.txt"
        problem.write_text("The curve is y = 5x.")
        self.write(entry_user("go"), entry_assistant("Now look at $y = 2x$."))
        self.assertIn("made-up-example", self.run_hook(env={"REPLY_CHECK_SOURCES": str(problem)}).stdout)

    def test_a_malformed_line_is_skipped(self):
        self.write(entry_user("the line is y = 3x + 1"), entry_assistant(GOOD), junk=True)
        self.assertEqual(self.run_hook().stdout, "")

    def test_no_transcript_and_bad_input_allow_the_stop(self):
        self.assertEqual(self.run_hook().stdout, "")
        self.assertEqual(self.run_hook(stdin="not json").stdout, "")

    def test_meta_lines_and_tool_results_are_not_prompts(self):
        self.write(
            entry_user("the line is y = 3x + 1"),
            {"type": "user", "isMeta": True, "message": {"content": "y = 2x"}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "content": "y = 2x"}]}},
            entry_assistant("Now look at $y = 2x$."),
        )
        self.assertIn("made-up-example", self.run_hook().stdout)

    def test_a_crash_allows_the_stop_and_is_logged(self):
        log = Path(self.folder.name) / "errors.log"
        code = (
            "import sys, reply_checker.stop_hook as hook\n"
            "def broken(_): raise RuntimeError('planted crash')\n"
            "hook.decide = broken\n"
            "sys.exit(hook.main())\n"
        )
        done = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            input="{}",
            capture_output=True,
            text=True,
            env={**os.environ, "REPLY_CHECK_LOG": str(log)},
        )
        self.assertEqual((done.returncode, done.stdout), (0, ""))
        self.assertIn("planted crash", log.read_text())


if __name__ == "__main__":
    unittest.main()
