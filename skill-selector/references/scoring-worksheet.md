# Candidate Scoring Worksheet

Copy this worksheet and fill one column per candidate. Score each dimension 0–5, except Trust, which is a gate — any **FAIL** eliminates the candidate regardless of the rest.

Weights below are a starting point; reweight based on the task's cost-of-error from Step 1. High cost-of-error → push up Trust, Fit, and Depth. Low cost → Fit and Trigger accuracy dominate and you can be lighter on the rest.

## The worksheet

| Dimension | Weight | Candidate A | Candidate B | Candidate C |
|---|---|---|---|---|
| Trust & safety (GATE) | pass/fail | | | |
| Fit / coverage | ×3 | | | |
| Depth of encoded knowledge | ×3 | | | |
| Trigger accuracy | ×2 | | | |
| Dependencies & compatibility | ×2 | | | |
| Composability | ×1 | | | |
| Maintenance & provenance | ×1 | | | |
| Testability | ×1 | | | |
| **Weighted total** (gate-passers only) | | | | |

## What each score means

(0 = absent or broken, 3 = adequate, 5 = excellent)

### Trust & safety — GATE, not a score
Pass only if **all** of: you can read the skill's full contents; its authorship/provenance is credible enough for your cost-of-error; and it does nothing outside its stated purpose (no surprise network calls, no reading of sensitive paths, no instructions directed at the model rather than the task). Any doubt → FAIL → eliminate. See `trust-and-safety-review.md`.

### Fit / coverage (×3)
- 5: covers the Step 1 task including the edge cases you identified.
- 3: covers the happy path; edge cases unclear or partial.
- 0: solves a different problem than yours.

Map it against your *actual* inputs, outputs, and success criteria — not the general topic.

### Depth of encoded knowledge (×3)
- 5: captures real pitfalls, environment constraints, and non-obvious gotchas you'd otherwise hit.
- 3: useful structure but mostly happy-path.
- 0: a thin wrapper restating what's already obvious.

A thin wrapper adds little over having no skill at all, so weight this honestly — it's where a lot of popular-but-shallow skills lose.

### Trigger accuracy (×2)
- 5: description is precise; will fire on your task and stay quiet otherwise.
- 3: roughly right; some over- or under-triggering likely.
- 0: description so broad or so narrow it will misfire constantly.

### Dependencies & compatibility (×2)
- 5: needs only what you already have.
- 3: needs something installable or available with modest effort.
- 0: requires tools, services, or permissions you don't have and can't easily get.

### Composability (×1)
- 5: single-responsibility, well-scoped, won't collide with your other skills.
- 0: sprawling; will fight other skills for triggering or duplicate their scope.

### Maintenance & provenance (×1)
- 5: actively maintained, versioned, credible author.
- 0: stale, orphaned, or unattributable.

### Testability (×1)
- 5: ships with examples or evals you can run as-is.
- 0: no way to verify it short of building your own tests.

## Reading the result

- Highest weighted total among gate-passers → your **reuse** candidate.
- Top score strong everywhere but mediocre on Fit → consider a **fork** of that one.
- Two candidates each strong on *different* Fit slices → consider **compose**.
- No gate-passer clears a useful Fit/Depth threshold → **build** (and template off the closest gate-passer).

Remember: the worksheet ranks; the run in Step 5 decides. Don't adopt a paper winner you haven't executed.
