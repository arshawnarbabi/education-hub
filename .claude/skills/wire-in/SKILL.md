---
name: wire-in
description: Wires a change into this project for real, whether it is a rule, an addition, an update or a new feature. Finds the one owner of the rule, makes every place that must know point at it, makes something block or fire when the behavior is skipped, proves it with a test that plants a violation, and reports what is enforced and what stays judgment. Use when asked to wire something in or to enforce a rule, or when asked whether something is actually enforced.
---

# /wire-in: a change lands everywhere it must, and something makes it happen

A shortened, generic version of a skill from a larger private project. The bar: a change is done only when each behavior it asks for is enforced, or is named as judgment only with the reason nothing stronger fits. "Written into the files" and "it should catch it" are never done. See `docs/enforcement.md`.

## The kinds, strongest first

- **BLOCKS:** a tool the behavior goes through refuses the wrong version.
- **FIRES:** something reads the state and keeps reporting until the behavior is done.
- **DECLARED:** a judgment no tool can make, made visible. The tool refuses unless the choice comes with a reason, and refuses a blank reason.
- **PROMPTED:** a hook prints the rule when it applies. A skip is still silent.
- **TEXT:** a file says it, and nothing else happens.

Enforced means BLOCKS, FIRES or DECLARED, each with a test. PROMPTED and TEXT are never called enforced.

## Step 0: the change and the baseline

1. Write the change in one line, in the requester's words, and name its kind.
2. Additions only: a change adds to the system. Altering other existing behavior needs an explicit yes, asked in one line.
3. Run every test suite and keep what was already red, so nothing red gets blamed on this change and nothing it broke hides behind an old failure.

## Step 1: one owner

Find the one file and heading that owns this rule, by meaning, starting with whether an owner already says it. Often the ask is a rule that exists and is not enforced yet; then that rule is the owner and no second one gets made. Everything else points at it. For an update, hunt every copy of the old version, including comments and printed messages.

## Step 2: every place that must know

Find them by meaning, not only by grep: a keyword hit that says something else is not a match, and a paragraph that means the same thing in other words is. Replace copies with a pointer to the owner. Where a copy has to stay (a hook message), tie it to the owner with a test.

## Step 3: make it happen, and prove it

1. List what already blocks or fires near this behavior. Extending a mechanism beats adding a second one.
2. Take the strongest kind that fits. Put a finding in the quietest place that still catches the skip before it costs anything.
3. Give every refusal a declared way out, or say in one line why no such case can exist. Check a declaration against the rest of the call, so it cannot contradict what the call says.
4. Key new refusals on something new, so calls already in use keep working. Stored records stay as they are; count the ones the new rule would have caught and report them.
5. Write the test, on a temporary fixture:
   - the violation is planted and refused;
   - the compliant twin passes;
   - a blank reason is refused;
   - it fails against a mutant with the mechanism removed. Add the mutant to `tools/mutation_check.py`.
6. Where a slip costs the most, test the edges too: boundary values, every other path to the same tool, each refusal that already exists on the same command, and every shape a stored record takes.

## Step 4: nothing in use breaks

Run what is in use, unchanged, before and after: the commands the docs write and the scripts that read what changed. A new step that builds state logs its errors where a check reads them, never to `/dev/null`.

## Step 5: verify

All suites pass, and each mutant is caught (`make prove`). For anything a person reads, build one real piece with the change and have a fresh agent grade it rule by rule, quoting it, without seeing the tests. Each rule it fails while every check passed is a gap: turn its evidence into a planted test and fix the mechanism. A rule still failing goes under Judgment only.

## Step 6: the report, short

1. **Owner:** the file and heading.
2. **Places updated:** one line each, then each place checked that needed no change, with the reason.
3. **Enforced:** each behavior with its kind, its mechanism and the test that proves it. A mechanism with no test line is not enforced.
4. **Judgment only:** each behavior that stays PROMPTED or TEXT, and why nothing stronger fits.
5. **Already red before:** what failed in the baseline.
6. **Needs a yes:** each edit to existing behavior the request did not cover. Nothing here was done.

Never call a PROMPTED or TEXT behavior enforced, and never report a test as passing that did not run in this session.
