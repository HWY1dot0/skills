# Decision ledger — where Step 6 lands

One line per decision, append-only. Before any new selection, Step 2 greps this
file first (Tier −1): if the task was already decided once, reuse the *decision*,
not just the skill. Re-evaluate only when the task or environment has changed.

Copy this file to `decisions.md` (git-ignored — it's your personal record) or just
let your agent create it on first use.

Format: `- YYYY-MM-DD · task keywords · verdict(reuse:X / fork:X / compose:X+Y / build:X) · one-line reason (test result / why others lost)`

---

- 2026-01-15 · pdf form filling · reuse:pdf-form-filler(claude-office-skills) · passed 3/3 shared cases; runner-up flaky on checkbox case; trust gate PASS
- 2026-02-02 · chart house-style · compose:advisor-skill+in-house renderer · no single candidate covered both judgment and rendering; composed after 2-case run-off
