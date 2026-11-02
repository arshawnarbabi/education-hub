"""Reply checker: planted violations, compliant twins, blank reasons, and the false holds that shaped the rules."""
import unittest

from reply_checker import Context, check
from reply_checker import curves, render, rules, signs


def kinds(reply, **context):
    return [finding.kind for finding in check(reply, Context(**context))]


EXPLANATION = """Start from the line you wrote.

$$y - 3 = 7$$

Add 3 to both sides, and watch the sign of the 3 change.

$$y = 7 + 3$$

**So y is 10.** Which sign changed?"""


class NoPicture(unittest.TestCase):
    def test_explanation_with_no_picture_is_held(self):
        self.assertIn("no-picture", kinds(EXPLANATION))

    def test_twin_with_a_picture_passes(self):
        self.assertEqual(kinds(EXPLANATION, picture_shown=True), [])

    def test_declared_reason_passes(self):
        reply = EXPLANATION + "\n\nNo picture: the student asked for words only"
        self.assertNotIn("no-picture", kinds(reply))

    def test_blank_reason_is_still_a_finding(self):
        for reason in ("", "ok"):
            findings = check(EXPLANATION + "\n\nNo picture: " + reason)
            blank = [f for f in findings if f.kind == "no-picture"]
            self.assertEqual(len(blank), 1)
            self.assertIn("blank reason", blank[0].detail)

    def test_a_short_answer_is_not_an_explanation(self):
        self.assertNotIn("no-picture", kinds("Yes, that is right. What is next?"))


class QuestionsAreNotExplanations(unittest.TestCase):
    """False hold: closed recall questions looked like an explanation, and a picture would give away the answers."""

    QUESTIONS = "Two questions from memory.\n\n1. What is $x$ when $x + 2 = 5$?\n\n2. What is $y$ when $2y = 8$?\n\n## Which one is harder?\n\n$$3z = 9, z = ?$$"

    def test_recall_questions_are_not_held(self):
        self.assertTrue(rules.asks_only(self.QUESTIONS))
        self.assertNotIn("no-picture", kinds(self.QUESTIONS))

    def test_a_question_that_works_it_out_still_counts(self):
        worked = EXPLANATION.replace("Which sign changed?", "Does that make sense?")
        self.assertFalse(rules.asks_only(worked))
        self.assertIn("no-picture", kinds(worked))

    def test_a_question_with_the_answer_inside_is_not_asks_only(self):
        self.assertFalse(rules.asks_only("Since $x = 3$, we get $y = 6$, right?"))


class AboutTheTool(unittest.TestCase):
    """False exemption: an early version let the word 'system' switch the rules off in a math question."""

    def test_math_with_tool_like_words_keeps_every_check(self):
        for prompt in ("solve the system of equations", "what is a reducing agent", "the hook of the curve"):
            self.assertFalse(rules.about_the_tool(prompt), prompt)
            self.assertIn("no-picture", kinds(EXPLANATION, prompt=prompt))

    def test_a_question_about_the_tool_is_left_alone(self):
        for prompt in ("why did the stop hook fire", "is the checker broken", "how does the system decide"):
            self.assertTrue(rules.about_the_tool(prompt), prompt)
            self.assertNotIn("no-picture", kinds(EXPLANATION, prompt=prompt))

    def test_render_bugs_still_count_when_exempt(self):
        self.assertIn("render", kinds("The answer is $5$.", prompt="why did the stop hook fire"))


class MadeUpExamples(unittest.TestCase):
    SOURCE = "Find the area between y = 21 - x and the x axis."

    def test_foreign_curve_is_held_with_or_without_example_words(self):
        for reply in ("Suppose $y = 2x$ instead.", "Now look at $y = 2x$."):
            self.assertIn("made-up-example", kinds(reply, sources=self.SOURCE))

    def test_the_problems_own_curve_passes(self):
        self.assertNotIn("made-up-example", kinds("Now look at $y = 21 - x$.", sources=self.SOURCE))

    def test_the_same_curve_rewritten_passes(self):
        self.assertNotIn("made-up-example", kinds("Solve for x: $x = 21 - y$.", sources=self.SOURCE))

    def test_example_words_are_caught_with_no_known_source(self):
        self.assertIn("made-up-example", kinds("For example, $y = 2x$ is simpler."))
        self.assertNotIn("made-up-example", kinds("Look at $y = 2x$."))

    def test_declared_reason_passes(self):
        reply = "Suppose $y = 2x$ instead.\n\nMade-up example: the student asked for a simpler curve"
        self.assertNotIn("made-up-example", kinds(reply, sources=self.SOURCE))

    def test_blank_reason_is_a_finding(self):
        reply = "Suppose $y = 2x$ instead.\n\nMade-up example:"
        self.assertTrue(any("blank reason" in f.detail for f in check(reply, Context(sources=self.SOURCE))))

    def test_one_use_only(self):
        found = kinds("Back to $y = 2x$.", sources=self.SOURCE, earlier_made_up={"2x"})
        self.assertIn("reused-example", found)
        self.assertNotIn("made-up-example", found)

    def test_naming_a_past_mistake_when_asked_about_the_tool_is_fine(self):
        found = kinds("I used a made-up $y = 2x$ there.", sources=self.SOURCE, prompt="why did the checker fire")
        self.assertNotIn("made-up-example", found)
        self.assertNotIn("reused-example", found)


class CurveReading(unittest.TestCase):
    def curve(self, text):
        return curves.equations(text)[0]

    def test_latex_forms(self):
        for text, x, expected in (
            (r"$y = \frac{x + 1}{2}$", 3.0, 2.0),
            (r"$y = \sqrt{x}$", 4.0, 2.0),
            (r"$y = 2x^2$", 3.0, 18.0),
            (r"$f(x) = x(x + 1)$", 2.0, 6.0),
        ):
            python = self.curve(text).python
            self.assertAlmostEqual(eval(python, {"__builtins__": {}, "x": x, "sqrt": lambda v: v ** 0.5}), expected)

    def test_rewrites_match_and_different_curves_do_not(self):
        self.assertTrue(curves.same_curve(self.curve("$y = 2x + 2$"), self.curve("$x = (y - 2)/2$")))
        self.assertFalse(curves.same_curve(self.curve("$y = 2x$"), self.curve("$y = 3x$")))

    def test_unreadable_input_never_reaches_eval(self):
        for hostile in ("__import__('os')", "x.__class__", "open(x)", "lambda: x", "(1).real"):
            self.assertIsNone(curves.to_python(hostile), hostile)

    def test_the_ast_check_stands_on_its_own(self):
        """A second layer, tested apart from the parser in front of it, so it cannot be removed unnoticed."""
        for hostile in ("__import__('os')", "x.__class__", "(lambda: x)()", "[x for x in y]", "'text'"):
            self.assertFalse(curves._is_safe(hostile), hostile)
        self.assertTrue(curves._is_safe("sqrt(x)+2*y**2"))

    def test_a_number_is_not_a_curve(self):
        self.assertEqual(curves.equations("$y = 5$"), [])


class RenderBugs(unittest.TestCase):
    def found(self, text):
        return [kind for kind, _ in render.problems(text)]

    def test_each_bug(self):
        self.assertIn("bare-number", self.found("It is $5$."))
        self.assertIn("word-span", self.found("Then $dx$ is small."))
        self.assertIn("digit-close", self.found("So $x$2 is wrong."))
        self.assertIn("inline-color", self.found(r"The ${\color{red}{u}}$ term."))
        self.assertIn("unclosed", self.found(r"Open $\frac{1}{2} and never close."))
        self.assertIn("space-open", self.found("A $ x$ span."))
        self.assertIn("bbox", self.found(r"$$\bbox[red]{x}$$"))
        self.assertIn("unbalanced-braces", self.found(r"$$\boxed{x = 1$$"))

    def test_left_alone(self):
        for text in ("It costs $29.68 total.", "From $4,000 to $12,000.", "`$5$` is code.", "$$5$$", "One $x$ here.",
                     r"Then $x = 5$ and $24\pi$."):
            self.assertEqual(self.found(text), [], text)


class SignMoves(unittest.TestCase):
    def test_term_across_equals(self):
        self.assertEqual(signs.sign_moves("y - 3 = 7", "y = 7 + 3"), ["-3 became +3"])

    def test_distributed_minus(self):
        self.assertTrue(signs.sign_moves("y = 5 - (x + 1)", "y = 5 - x - 1"))

    def test_unrelated_equations_are_no_move(self):
        self.assertEqual(signs.sign_moves("y = 2", "x = 9"), [])

    def test_held_only_in_style_when_signs_are_unmentioned(self):
        without = "Next.\n\n$$y - 3 = 7$$\n\nThen\n\n$$y = 7 + 3$$\n\n**Done.** Next?"
        self.assertIn("no-sign-check", kinds(without, picture_shown=True))
        self.assertNotIn("no-sign-check", kinds(EXPLANATION, picture_shown=True))


class Style(unittest.TestCase):
    def test_heading_must_be_a_question_or_a_job(self):
        self.assertIn("heading", kinds("## The setup\n\nOk."))
        self.assertNotIn("heading", kinds("## What is the radius?\n\nOk."))
        self.assertNotIn("heading", kinds("## Square the radius\n\nOk."))

    def test_no_bold(self):
        self.assertIn("no-bold", kinds(EXPLANATION.replace("**", ""), picture_shown=True))

    def test_long_paragraph(self):
        long_reply = EXPLANATION + "\n\n" + "word " * 70 + "\n\nNext?"
        self.assertIn("long-paragraph", kinds(long_reply, picture_shown=True))

    def test_inline_equation(self):
        reply = EXPLANATION.replace("**So y is 10.**", r"**So y is** $y = \frac{a + b + c + g}{d + e + f + h}$ in the end.")
        self.assertIn("inline-equation", kinds(reply, picture_shown=True))

    def test_yes_before_but(self):
        self.assertIn("yes-before-but", kinds("Yes. But the sign is wrong."))
        self.assertNotIn("yes-before-but", kinds("Yes. Go on."))

    def test_no_lead_in(self):
        reply = "Here.\n\n$$y = 1$$\n\n$$x = 2$$\n\n**Done.** Next?"
        self.assertIn("no-lead-in", kinds(reply, picture_shown=True))
        chain = "Here.\n\n$$y = 1$$\n\n$$= 2$$\n\n**Done.** Next?"
        self.assertNotIn("no-lead-in", kinds(chain, picture_shown=True))

    def test_no_ask(self):
        self.assertIn("no-ask", kinds(EXPLANATION.replace("Which sign changed?", ""), picture_shown=True))

    def test_style_never_holds(self):
        for finding in check("## The setup\n\nYes. But no."):
            self.assertFalse(finding.is_stop, finding.kind)


if __name__ == "__main__":
    unittest.main()
