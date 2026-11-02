# What failed, and what changed

These come from building the private system. Where the fix is in this repo, the test that covers it is named.

**A rule that was only written down.** Each problem type was supposed to have a ladder of variants. Nothing checked, so types built up with no rungs, and attempts at harder versions got logged with no rung name and scored as the base. The status looked fine and was wrong. Now a cold attempt on a type with rungs is refused unless it names one or declares why none fits, and a solved type with a short ladder keeps getting reported. Tests: `RungRule`, `LadderShort`.

**An exemption that was too broad.** Questions about the tool itself are exempt from the teaching rules, and that exemption started as a keyword list including "system", "agent" and "hook". So "solve the system of equations" switched off every check. Each word now counts only next to a word that makes it about the tool. Test: `AboutTheTool`.

**A false hold on questions.** Two recall questions with math in them looked like an explanation, and got held for having no picture. A picture there would have given away the answers. The classifier now asks what the reply does: if all its math sits in questions and nothing is worked out, it is not an explanation. Keyed on structure, not on a phrase. Test: `QuestionsAreNotExplanations`.

**A first miss that never came back.** A problem type used to get registered only after its first right answer. A type missed on the first try never entered the review queue, which is the opposite of what a review queue is for. Types now register on the first attempt, right or wrong. Test: `Daily.test_a_type_missed_on_its_first_solo_still_comes_back`.

**A silent failure.** One record stored a field as a list where a string was expected. A rebuild step crashed on it every run, its errors went to `/dev/null`, and a whole class of reminders stopped for days with nothing reporting it. The rule since: a step that builds state skips one bad record instead of dying on it, logs errors to a file a check reads, and has its output's freshness checked. Tests here: `StopHook.test_a_malformed_line_is_skipped`, `StopHook.test_a_crash_allows_the_stop_and_is_logged`.

**Passing tests, wrong output.** A sample reply passed every automated check and a fresh agent still found rules it broke, because planted tests only cover what the builder thought of. This led to the blind judge step in [enforcement.md](enforcement.md). It catches more, and it costs more to run, so it is used only on things a person reads.

**A regression from a runtime difference.** Hooks ran under an older Python than the rest of the system. `datetime.fromisoformat` rejects a trailing `Z` before 3.11, and one stored row with that form crashed a check. Test: `Regressions`.

**A checker that grew by wrapping.** A standing rule was that changes only add and never alter what already works. It kept existing behavior safe. It also meant new checks got layered on as wrappers around older functions, in one very large file, and that file got hard to read. It is not offered here as an example of good structure. The checker in this repo is a rewrite of its core into small flat modules, not a copy. The tradeoff was deliberate, and the cost is still there in the private version.

**A gap this repo's own mutation check found.** On its first run, `tools/mutation_check.py` reported one mutant missed: removing the `ast` whitelist in `curves.py` broke no test, because the hand parser in front of it rejected all the hostile inputs first. The whitelist now has a test of its own. This is the check doing its job, and it is why it exists.

## Limits that remain

* The reply rules are heuristics over text, built from regular expressions and sample points. They will produce false holds and misses. A hold happens once and the model can declare a reason, so a false hold costs one turn, not a session.
* Hook decisions depend on Claude Code's transcript format and Stop hook behavior, which can change.
* The render list is specific to one chat client.
* Nothing here measures whether any of this helps someone learn. There is no such claim in this repo.
