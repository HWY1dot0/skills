# Comparing Effectiveness

How to actually measure which candidate performs best, instead of guessing from descriptions or popularity. This is the step that decides; everything before it only narrows the field.

Core principle: **all candidates run the same test set, and you judge them against your Step 1 success criteria — not against each other's vibes.** A skill that "looks thorough" can lose to a plain one that simply produces the right output.

## 1. Build one shared test set

Turn the Step 1 task definition into 2–5 concrete test cases — the *same* cases for every candidate. A test case is a realistic input plus the success criteria for its output. Cover the edge cases you identified, not just the happy path; edge-case behavior is usually where candidates diverge. Save them once and reuse them across all candidates and all iterations.

## 2. Run every candidate on it

Pick the mode that matches your environment.

### Mode A1 — Workflow orchestration (Claude Code, zero external deps)

`scripts/compare_run.workflow.js` is a ready-made Workflow template: the main agent reads the
cases and candidate paths, passes them as `args`, and the workflow runs every
(candidate × case × repeat) through an isolated runner agent — each runner sees ONLY its
candidate's SKILL.md and must report `blocked` rather than improvise beyond it — then a
**blind judge** (sees anonymized artifacts + criteria, never the candidate name, defaults to
fail) scores each run. Returns a pass matrix, per-candidate totals, flaky-case flags, and a
verdict hint. Repeats ≥2 so consistency is measured, not assumed. This is the default path.

### Mode A2 — skill-creator's eval harness (when you want full benchmark reports)

The harness at the installed `skill-creator` plugin supports N candidates natively via the
**candidate = configuration** mapping (verified against its code, 2026-07-03):

1. Per test case, write `<ws>/iteration-1/eval-N/eval_metadata.json` = `{eval_id, eval_name, prompt, assertions[]}` (dirs must match glob `eval-*`).
2. Spawn one executor subagent per (eval × candidate): "Skill path: <candidate>; Task: <prompt>; Save outputs to `eval-N/<candidate_name>/run-1/outputs/`" — the **`run-1/` level is mandatory** (the aggregator globs `run-*` and silently skips configs without it). Don't name a candidate dir `inputs`/`outputs`.
3. Grade each run with its grader agent (`agents/grader.md`) → `grading.json` using the **exact field names `text`/`passed`/`evidence`** (the viewer breaks on variants).
4. From the skill-creator dir: `python -m scripts.aggregate_benchmark <ws>/iteration-1` then `python eval-viewer/generate_review.py … --static out.html`.
5. **Read rankings from `benchmark.json`'s `run_summary`** (has all N candidates, mean±stddev pass-rate/time/tokens). Ignore the viewer's top summary table and the delta stat — both are hardcoded to the first two configurations; the per-eval breakdown is fully N-way.

Use A2 over A1 when you want the HTML review UI, token/latency stats, or you're already in a skill-creator improvement loop. Its blind pairwise comparator (`agents/comparator.md`) is A/B-only — for 3+ candidates run it round-robin or just rely on assertion pass-rates.

### Mode B — Sequential (Claude.ai / no subagents)

No subagents means run them one at a time, by hand:

1. For each candidate: read its SKILL.md, then follow its instructions to complete each test case yourself.
2. Save each candidate's outputs to its own directory (`candidate-A/`, `candidate-B/`, …) so they can be compared.
3. Lay the outputs side by side and judge each against the success criteria.

Less rigorous than Mode A, but a real run still beats any amount of description-reading. The human (and the explicit criteria) compensate for the missing automation.

## 3. What to measure

In priority order:

1. **Correctness** — does the output meet the Step 1 success criteria? This dominates; a candidate that fails here can't be rescued by other metrics.
2. **Consistency** — run a couple of cases 2–3× each. A candidate that's right once but flaky is worse than a steady one. (Variance is invisible if you only run each case once.)
3. **Triggering** — for the reuse path, does the skill actually fire on your task and stay quiet otherwise?
4. **Cost / latency** — tokens and time, as a **tie-breaker** between candidates that are otherwise even. Never let a cheap-but-wrong candidate beat a correct one.

## 4. Community signal is a prior, not a verdict

A registry's usage leaderboard or star count (e.g. skills.sh telemetry) tells you what's broadly popular and trusted — useful for deciding **which candidates to test first** when you have many. It does **not** tell you what fits *your* task, your inputs, or your environment. Popularity has no vote in the final ranking; the run does.

## 5. Comparison matrix

Fill one row per candidate, one column per test case. Mark pass/fail (and a short note on *how* it failed), then summarize.

| Candidate | Case 1 | Case 2 | Case 3 | Consistency | Cost (tok/s) | Verdict |
|---|---|---|---|---|---|---|
| Candidate A | | | | | | |
| Candidate B | | | | | | |
| Candidate C | | | | | | |

- **Verdict** options map straight onto Step 4: *adopt* (passes all cases, trustworthy), *fork* (close but misses specific cases you could patch), *compose* (passes a subset that complements another candidate), or *reject*.
- If no candidate clears the correctness bar, the matrix has just justified **build** — and shows you exactly which cases a new skill must handle.

## The one rule

Rank on paper to triage; let the run decide. Don't ship a "winner" you selected from a description or a leaderboard without executing it against your own test set.
