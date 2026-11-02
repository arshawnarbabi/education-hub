# Instructions for Claude Code

Someone pasted this repo's link into Claude Code, or opened it here. Help them understand it and try it.

If they have not said what they want, do this:

1. Clone the repo if it is not already on their machine, and tell them where you put it.
2. Run `make demo` and walk them through the output in plain words.
3. Offer three things and let them pick: learn how it works, run the proof (`make test`, `make prove`), or add a part to their own project.

## Learning how it works

Answer from the code and these files, and point at the file and line you used:

- `README.md` for the overview
- `docs/design.md` for why it is built this way
- `docs/enforcement.md` for what is enforced and what is judgment
- `docs/what-failed.md` for what went wrong and what changed
- `.claude/skills/wire-in/SKILL.md` for the method

This repo is a cut-down version of a personal system. If they ask about something that is not here, say it is not in this repo. Do not guess at how the private version works.

## Adding a part to their own project

Ask first, say which files you will change, and change nothing outside what they approve.

- **Study engine:** copy `study_engine/` into their project and add `fsrs` from `requirements.txt` to their dependencies. Replace the sample course in `sample_data/` with their own material.
- **Reply checker:** copy `reply_checker/` into their project, then merge `examples/settings.stop-hook.json` into their `.claude/settings.json`. Tell them what it does before you add it: it runs at the end of every reply in that project and can send a reply back once to be fixed. Its rules are written for math tutoring, so they may want to change `reply_checker/rules.py`.
- **The method:** copy `.claude/skills/wire-in/` into their `.claude/skills/`.

After adding anything, run it once to show that it works. `make test` covers this repo only, so test the copy in their project directly.

Everything in `sample_data/` is made up. Never present it as real results.
