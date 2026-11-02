# Design notes

## The study engine

**Why not just use Anki?** Scheduling was never the gap, and this uses FSRS through the open source [`fsrs`](https://github.com/open-spaced-repetition/py-fsrs) package instead of reimplementing it. Anki also offers FSRS. The gap is the records around it, and that a coach in a chat can drive it without anyone opening another app. The tradeoff is that the dependency moves and does not disappear: the loop now depends on the chat being used.

**Four tables do the work.**

```
cards ---< reviews       one row per FSRS card; a review stores rating and correct apart
ptypes --< rungs         a kind of whole problem; the ways it can be asked
ptypes --< attempts      a scored item that is not a card; may link to a type and a rung
attempts >-- cards       a miss that exposed a real gap can become a card
```

**Rating and correctness are separate columns.** An FSRS rating is a scheduling input and can reasonably be generous. Accuracy has to stay strict or the numbers mean nothing. One column cannot do both jobs.

**Confidence comes before the key.** A rating given after seeing the answer is contaminated, and a store cannot detect that afterwards. So the rule is put at the point of logging: the rating is required, or a reason for its absence. The store cannot prove when the rating was given. That part stays a matter of process.

**Attempts and cards are different things.** Turning every quiz question into a card floods the deck, so correct answers stay attempts and only a miss that exposes a real gap becomes a card.

**Status is computed, never stored.** `mastery.solid_status` is a pure function of attempts and takes no database, so a status cannot disagree with the records and the rule has a test for each boundary. A type is solid when, since its last cold miss, it has two right cold attempts at least 6 days apart on two different versions, one of them not the base. Those numbers are a design choice, not a measured result.

**A doubted right answer is neither a pass nor a miss.** If a student gets it right and says they guessed, counting it as mastered is wrong and counting it as a miss is unfair, so it stays out of the arithmetic and the words get stored.

**Numbers report their sample size.** `stats.summarize` says "too few to claim anything" under 20 items. It is a blunt bar, and that is the point. A rate from a handful of items should not read like a finding.

## The reply checker

**Why a Stop hook.** Instructions to a model get followed most of the time, and the rest is what a check is for. Claude Code runs a Stop hook when the model finishes a turn. If the hook prints a block decision with a reason, the reason goes back to the model and the turn continues, so a correction lands before the person moves on. See [`reply_checker/stop_hook.py`](../reply_checker/stop_hook.py).

**Why hold once.** Claude Code sets `stop_hook_active` on the stop after a hold. The hook goes silent there, so a rule that cannot be met costs one extra turn and can never trap a session.

**Why fail open.** A crash in the hook allows the stop and writes a log file. A broken checker must not block a session, and its errors still have to surface somewhere.

**Why read the transcript.** Whether a picture was shown comes from the tool calls in the transcript, not from what the reply claims.

**Why compare curves by value.** A tutor rewriting $y = 21 - x$ as $x = 21 - y$ is teaching, not inventing. Text comparison would flag it. So the checker parses each right-hand side and tests sample points of one curve on the other. Parsing goes through a hand tokenizer, then an `ast` whitelist, then `eval` with no builtins.

**Declared ways out.** No rule fits every case, and a rule that fires where it does not apply gets ignored. So each STOP rule that can reasonably not apply takes a line such as `No picture: the student asked for words only`. A reason under two words is itself a finding. A skip is always on the record.

## What the sample leaves out

This is a cut-down core. The private checker has many more rules tied to one person's courses and pictures, and those were left out instead of generalized. The hook here decides on the STOP group only; style findings come from `python3 -m reply_checker`.
