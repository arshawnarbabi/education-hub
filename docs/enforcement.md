# How a rule gets enforced

The problem this answers: a rule written into an instruction file for an AI agent is a request, and agents skip requests. The private system had rules that were written down, reported as done, and still slipped. So "done" got a stricter meaning, and the procedure for meeting it became a Claude Code skill, [`.claude/skills/wire-in/SKILL.md`](../.claude/skills/wire-in/SKILL.md). That file here is a shortened, generic version.

## Five kinds, strongest first

| Kind | What it means | Counts as enforced | Example in this repo |
|---|---|---|---|
| BLOCKS | a tool the behavior goes through refuses the wrong version | yes | `Store.review` refuses a review with no confidence rating |
| FIRES | something reads the state and keeps reporting until it is fixed | yes | `Store.daily` lists a short ladder until the rungs exist |
| DECLARED | a judgment no tool can make, made visible: skipping needs a reason, and a blank reason is refused | yes | `no_rung="..."` on an attempt, `No picture: ...` in a reply |
| PROMPTED | a hook prints the rule when it applies, whether or not it gets followed | no | not used in this core |
| TEXT | a file says it, and nothing else happens | no | the STYLE findings are close to this: reported, never held |

PROMPTED and TEXT can be useful, but a skip stays silent, so they are never called enforced.

## What proves a mechanism

Each one needs all four:

1. **A planted violation.** The bad input is refused or the check fires.
2. **A compliant twin.** The same call with what the rule asks for passes. Only this catches a refusal so broad it blocks correct work.
3. **A blank reason.** Where there is a declared way out, an empty reason is refused.
4. **A mutant.** With the mechanism removed, the test fails. A test that still passes is not testing the rule.

Step 4 is automated in [`tools/mutation_check.py`](../tools/mutation_check.py). It copies the repo, makes one exact text replacement that removes a mechanism, and runs the suite that claims to cover it. It stops if a replacement no longer matches the source, so its list cannot go stale.

```
make prove
```

## Choosing where a finding shows up

A check that interrupts on every message gets ignored, so a finding goes in the quietest place that still catches the skip before it costs anything. That is why the reply checker has two groups. STOP findings hold the reply, and STYLE findings only report. The private system adds backstops at end-of-session sweeps for the same reason.

## Keeping old behavior working

New refusals key on something new (a new argument, or a record dated after a cutoff), so commands already in use keep working and stored records are never rewritten to fit a new rule. Records the new rule would have caught get counted and reported.

## What tests cannot prove

Planted tests cover the cases the builder thought of. In the private system a sample reply passed every check and a fresh agent, given only the rules and the output and not the tests, still found rules it broke. So for anything a person reads, the procedure adds a **blind judge**: an agent that wrote none of the mechanism grades a real output rule by rule, quoting it as evidence. Each rule it fails while every check passed is a gap, and it becomes a new planted test. A rule still failing at the end gets listed as judgment only.

That step is a process, not code, so this repo cannot demonstrate it with a command.

## Rules and mechanisms in this repo

| Behavior | Kind | Test class | Mutant |
|---|---|---|---|
| review needs confidence or a reason | BLOCKS, DECLARED | `ConfidenceRule` | review with no confidence rating; blank reason for no confidence |
| delayed attempt needs confidence or a reason | BLOCKS, DECLARED | `ConfidenceRule` | delayed attempt with no rating |
| rating never leaks into `correct` | structure | `RatingAndCorrectStayApart` | generous rating leaks into correct |
| doubt words lower the rating | structure | `RatingAndCorrectStayApart` | doubt words ignored |
| cold attempt names its rung | BLOCKS, DECLARED | `RungRule` | cold attempt with no rung; blank reason for no rung |
| solid needs a gap, variety and no miss since | computed | `SolidStatus` | solid without a time gap; solid without variety; a miss does not reset the count |
| short ladder is reported | FIRES, DECLARED | `LadderShort` | short ladder finding removed |
| small samples say so | structure | `Stats` | small samples stated as fact |
| explanation needs a picture | FIRES at the Stop hook, DECLARED | `NoPicture` | explanation with no picture; blank declared reason accepted |
| made-up curve | FIRES at the Stop hook, DECLARED | `MadeUpExamples` | made-up curve allowed; rewritten curve counted as foreign |
| hook holds once and fails open | structure | `StopHook` | hook holds forever; hook ignores the rules; hook crash goes unlogged |
