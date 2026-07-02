# Collecting Candidates

How to turn "go find skills for this task" into a concrete candidate list. Work the tiers below from cheapest to broadest, stop once you have 2–5 genuinely relevant candidates, and route everything you pull from outside your own environment through `trust-and-safety-review.md` before it can be scored.

The ecosystem moves fast, so treat the named sources here as **starting points to verify at runtime**, not a frozen or exhaustive list. Discover current registries with a quick web search rather than assuming this file is up to date.

## Search by capability, not by name

Before searching anywhere, restate the task from Step 1 as **verbs + nouns + I/O formats**: "fill PDF form fields", "extract tables from xlsx", "generate a slide deck from an outline". Search those. Names are unreliable (skills are named by their authors, not by your task); capability and input/output type are what actually predict fit.

## Tier 0 — Skills already loaded

The skills the agent can already see (its available-skills list) are zero-cost and pre-trusted. Check these first; the answer may already be in front of you. If one fits, you can often skip the rest of this file.

## Tier 1 — Local skill directories

Skills installed in the environment live on the filesystem (commonly under a `skills/` tree). Inventory them concretely:

```bash
python scripts/inventory_skills.py /path/to/skills
```

This prints every skill's name, description, and path — a scannable shortlist. Use `--json` to pipe the inventory into later steps. The same script works on any directory, including a registry repo you've downloaded (Tier 2).

## Tier 2 — Public registries and the official catalog

**The fast path: `scripts/fetch_candidates.py "<query 1>" "<query 2>" …`.** It fans the
queries across multiple sources (SkillsMP + agentskill.work + GitHub code search when `gh`
is authenticated), dedupes and collapses repo-floods, **ranks by query relevance first and
stars second**, resolves each lead to its canonical GitHub source, downloads each candidate's
*full* skill directory into a sandbox, then **re-ranks on SKILL.md full text** (descriptions
are marketing; full text is evidence). Use `--include-voltagent` to also fold in the curated
awesome-list, `--no-gh` to skip code search, `--limit N`, `--no-download`, `--no-canonical`.
The downloaded files are exactly what Step 3's trust gate reads — nothing is adopted
sight-unseen.

**Every live source is LEXICAL — none does semantic search** (verified 2026-07: three
phrasings of one capability shared *zero* results on SkillsMP). Two consequences: (1) always
pass 2–4 query variants phrased the way authors name skills ("fill pdf form", "pdf form
filler") — generating variants is the agent's job, the script unions them; (2) trust the
script's relevance re-rank over any source's own ordering.

**Registries are LEADS, not truth — always land on the author's GitHub.** Hard-won the
expensive way: a registry's star count is often that of a *vendored copy* buried in someone
else's monorepo (★0), not the author's own repo (★732 for the same skill); and the path a
registry points at is sometimes already 404. So the fetcher, for every lead, reads the REAL
GitHub stars, verifies the SKILL.md path is still live, and — when a lead looks vendored or
its path is dead — searches GitHub (star-sorted, broad, since the canonical repo may be a
multi-skill repo whose *name differs from the skill*) and redirects to the highest-star repo
that actually contains the skill. Each candidate is tagged `provenance`:
`registry-verified` / `vendored→canonical` / `dead→canonical` / `github-verified (real ★)` /
`dead-404`. Treat a leaderboard number you have not confirmed against the source repo as
marketing, not evidence.

The source landscape (probed live 2026-07-03 — **re-verify at runtime, it moves fast**):

- **GitHub code search** (via authed `gh` CLI; auto-enabled in the script) — **the strongest
  lane**: `gh search code --filename SKILL.md "<keywords>"` matches file *content*, where
  registries only match names/descriptions. Anonymous is a hard 401; the code_search bucket
  is 10 req/min authed, so budget ~8 calls per discovery run. Results are broad and include
  junk (forks, recycle bins) — the script's full-text re-rank and the trust gate filter those.
- **SkillsMP** (`skillsmp.com/api/v1/skills/search`) — primary registry, anonymous REST over
  tens of thousands of scraped skills. Quota **50/day + 10/min**, self-reported via
  `x-ratelimit-*` headers (the script prints remaining). Search is lexical; `sortBy=stars`
  doesn't even star-sort reliably, and stars are REPO-level — benchmark monorepos flood
  results with machine-generated near-dupes at shared inflated stars (script collapses to
  2/repo). Extra params exist: `category`, `occupation`, `sortBy=recent`, `page` (see
  /openapi.json); there's also an MCP server at skillsmp.com/mcp and an `/api/timeline`.
  No list-all or per-skill detail endpoints — search is the only route.
- **agentskill.work** (`/api/skills?q=&limit=`) — secondary, wired in. Anonymous JSON,
  repo-level index refreshed from GitHub; every item carries canonical `html_url`, stars,
  topics, `quality_score`, `verification_status`, `last_pushed_at`. Caveats: strict lexical
  AND (multi-word query often → 0; the script auto-retries per-keyword), and repo-level
  granularity means huge framework repos match broad terms — the relevance re-rank handles it.
- **openagentskill.com** (`/api/skills/search?q=`, `/api/agent/resolve?task=`) — anonymous
  and returns GitHub URLs, but its corpus is **star-scraped general repos that mostly are
  not skills** (markitdown, crawl4ai as "skills"). Not wired in: use manually as a lead
  generator only, and always verify a SKILL.md actually exists at the target.
- **skills.sh** (Vercel) — still 401 OIDC-gated on every endpoint (rechecked 2026-07-03).
  Not usable anonymously.
- **skillregistry.io** — `/api/skills` ignores its `q` param (returns all ~61 items); most
  entries lack GitHub sources. Skip, or treat as a one-shot dump to filter locally.
- **AgentSkillsHub** (`agentskillshub.top`) — still UI-only, no public API.
- **VoltAgent/awesome-agent-skills** — curated awesome-list README; `--include-voltagent`.
- **Curated multi-skill repos via topic search** — `gh api 'search/repositories?q=topic:agent-skills&sort=stars'`
  (works even anonymous, 10/min) surfaces the big libraries worth browsing directly:
  anthropics/skills (official), ComposioHQ/awesome-claude-skills, addyosmani/agent-skills,
  VoltAgent/awesome-agent-skills, sickn33/antigravity-awesome-skills, alirezarezvani/claude-skills,
  K-Dense-AI/scientific-agent-skills. Topic tags are self-applied — verify a hit actually
  contains SKILL.md files (`inventory_skills.py` on a shallow clone) before treating it as a
  skill library.
- **Partner / vendor directories** — first-party skills from vendors (Atlassian, Canva,
  Figma, Notion, Ramp, Sentry, …). If your task touches a specific product, that vendor's
  own skill is usually the highest-fidelity option.

To evaluate a candidate the script didn't fetch (or to grab a whole repo), pull it into a
sandbox by hand and confirm what's inside:

```bash
git clone --depth 1 <repo-or-skill-url> /tmp/candidate-<n>
python scripts/inventory_skills.py /tmp/candidate-<n>
```

Then read its SKILL.md and every bundled file. Anything you can't read is an automatic
trust FAIL — and note that stars rank *popularity, not safety*: a live test run surfaced a
high-star candidate whose repo was a malware-benchmark dataset. Provenance is checked at the
Step 3 gate, never assumed from the leaderboard.

## Tier 3 — Open web search

For niche or domain-specific needs not covered above, search the web for `<capability> SKILL.md` or `<domain> agent skill`. Community skills are abundant but uneven in quality and unaudited — they go through the trust review like anything else, and you should weight provenance heavily (supply-chain risk on third-party skills is real).

## Before scoring: a clean candidate list

You should now have, for each candidate: its name, where it came from, its full readable contents pulled locally, and a one-line note on what task-slice it covers. That list — not a pile of browser tabs — is what feeds Step 3 scoring. If a "candidate" can't be read or run locally, it isn't a candidate yet.

## Don't forget the null result

If the tiers turn up nothing that fits, that *is* the finding: it points to **build** (Step 4), and the closest near-miss you found becomes the structural template. Coming up empty is a valid, useful outcome — not a reason to keep searching indefinitely.
