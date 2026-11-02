"""House rules for the repo itself, and the promise that the demo runs."""
import subprocess
import sys
import tokenize
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EM_DASH, EN_DASH = chr(0x2014), chr(0x2013)
BANG = chr(33)
SKIP_DIRS = {".git", ".venv", "__pycache__"}
TEXT_SUFFIXES = {".py", ".md", ".json", ".txt", ".toml", ".yml", ".yaml", ""}


def repo_files():
    for path in ROOT.rglob("*"):
        if path.is_file() and not SKIP_DIRS & set(path.parts) and path.suffix in TEXT_SUFFIXES:
            if path.name.endswith(".db"):
                continue
            yield path


class Punctuation(unittest.TestCase):
    def test_no_em_or_en_dashes_anywhere(self):
        for path in repo_files():
            text = path.read_text(encoding="utf-8")
            self.assertNotIn(EM_DASH, text, path)
            self.assertNotIn(EN_DASH, text, path)

    def test_no_exclamation_marks_in_prose(self):
        """Markdown outside the one marked comment, and Python comments and docstrings.

        Python operators and regular expression lookarounds are code, not prose.
        """
        for path in repo_files():
            if path.suffix == ".md":
                text = path.read_text(encoding="utf-8").replace(BANG + "--", "")
                self.assertNotIn(BANG, text, path)
            elif path.suffix == ".py":
                with tokenize.open(path) as handle:
                    for token in tokenize.generate_tokens(handle.readline):
                        if token.type == tokenize.COMMENT:
                            self.assertNotIn(BANG, token.string, f"{path}:{token.start[0]}")
                        if token.type == tokenize.STRING and token.string.startswith(('"""', "'''")):
                            self.assertNotIn(BANG, token.string, f"{path}:{token.start[0]}")


class ClaimsStayTrue(unittest.TestCase):
    """The README's numbers are checked here, so they cannot drift from the code."""

    def test_readme_counts_match_the_code(self):
        sys.path.insert(0, str(ROOT / "tools"))
        from mutation_check import MUTANTS

        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        tests = unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT)).countTestCases()
        self.assertIn(f"{tests} tests", readme)
        self.assertIn(f"{len(MUTANTS)} of {len(MUTANTS)} mutants", readme)


class Demo(unittest.TestCase):
    def test_demo_runs_and_says_its_data_is_made_up(self):
        done = subprocess.run([sys.executable, "demo.py"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("made up", done.stdout)
        self.assertIn("REFUSED", done.stdout)
        self.assertIn('"decision": "block"', done.stdout)

    def test_demo_output_is_deterministic(self):
        first = subprocess.run([sys.executable, "demo.py"], cwd=ROOT, capture_output=True, text=True).stdout
        second = subprocess.run([sys.executable, "demo.py"], cwd=ROOT, capture_output=True, text=True).stdout
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
