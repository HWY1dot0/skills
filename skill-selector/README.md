# skill-selector

**English** | [简体中文](README.zh-CN.md)

**A skill for choosing skills.** Given a task, decide whether to *reuse* an existing agent skill, *fork* one, *compose* several, or *build* new — with evidence, a security gate, and a token budget you control.

Works with [Claude Code](https://claude.com/claude-code) and any agent runtime that reads `SKILL.md` skills. The five helper scripts are pure Python stdlib — no dependencies, no LLM calls, each independently runnable.

## Why this exists

The agent-skill ecosystem is large and unaudited. Building this tool (and testing it against the live ecosystem, mid-2026) surfaced four lessons that are now baked into the pipeline:

1. **Stars lie.** Registries often point at a vendored ★0 copy buried in someone's monorepo while the author's own repo has hundreds of stars — and sometimes the registry's link is already a 404. Every lead here is resolved to its *canonical* GitHub source with real stars before it's trusted.
2. **"Has a script" ≠ "the script does anything."** Hollow skills — functions that return hardcoded constants, empty bodies, `# Real implementation would…` — look identical to real ones from the description. The trust scanner detects them.
3. **A bad skill is worse than no skill.** Skills carry instructions the model will follow and code it may run. NVIDIA's research puts vulnerable skills at ~26% and likely-malicious at ~5%. Nothing here is adopted sight-unseen.
4. **No registry does semantic search.** Verified live: three phrasings of the same capability shared *zero* results. Recall and relevance are therefore enforced client-side — multi-source query fan-out plus two-stage re-ranking on full text.

## The funnel

```
grep decisions.md      Tier −1  was this already decided?           ~0 tokens
match_local.py         Tier 0   do I already have it locally?       ~1k
fetch_candidates.py    Tier 2   multi-source search + download      ~2k
trust_scan.py          gate     dangerous / injected / hollow?      ~ a few k
compare_candidates.py  static   side-by-side bench cards            ~1k
compare_run.workflow   run-off  blind-judged execution              heavy (see Modes)
```

Each layer exists to terminate the selection early. Most selections should end at Tier 0 with "you already have it."

## Modes — you pick the weight

| Mode | What runs | ~Tokens | Say |
|---|---|---|---|
| **light** | ledger + local match only | 2–5k | "quick check", "do I have something for…" |
| **standard** *(default)* | + multi-source fetch + trust gate + static compare | 30–50k | — |
| **thorough** | + blind execution run-off across candidates | 150k–700k | "compare them properly", "thorough" |

Three rules make the cost predictable:

- **Escalation needs consent.** The agent never enters the thorough tier uninvited. If static evidence can't separate two finalists, it stops and asks — with costs attached — rather than silently spending 600k tokens.
- **De-escalation is free.** A strong local match ends any mode at ~5k. Mode sets the ceiling, not the floor.
- **Headless runs never auto-escalate.** No one to consent, no run-off.

## The toolkit

| Piece | Job |
|---|---|
| `SKILL.md` | The six-step decision framework the agent follows (gate → define → collect → score → decide → validate → record) |
| `scripts/match_local.py` | Rank *installed* skills & slash-commands against a task. Bilingual (EN/中文) lexical matching, concept normalization, IDF weighting. Follows symlinked installs. |
| `scripts/fetch_candidates.py` | Multi-source search (SkillsMP + agentskill.work + GitHub **code search** of SKILL.md content when `gh` is authed), repo-flood collapse, relevance-first ranking, canonical-source resolution, sandbox download, full-text re-rank. Self-throttles on quota headers; distinguishes rate-limits from dead links. |
| `scripts/trust_scan.py` | Deterministic security gate: dangerous calls (AST-level), network+secret exfil combos, prompt-injection phrasing, invisible/bidi characters, base64 blobs, hollow-stub detection, and an explicit report of what it *couldn't* scan. `--baseline` suppresses previously-reviewed findings on re-scans. |
| `scripts/compare_candidates.py` | Static bench cards: trust verdict, real-code vs stub ratio, deps, examples. |
| `scripts/compare_run.workflow.js` | The thorough tier (Claude Code Workflow): every candidate × case × repeat runs in an isolated agent that may use *only* that candidate's guidance, then a **blind judge** scores artifacts against your success criteria. Early-stops when round 1 is decisive (~50% cheaper). Returns a pass matrix + flaky flags. |
| `scripts/inventory_skills.py` | Plain listing of every SKILL.md under a directory. |
| `decisions.example.md` | Template for the append-only decision ledger — every recorded decision makes the next selection cheaper (Tier −1). |

## Security model

Two scanners, deliberately different jobs:

- **`trust_scan.py`** (bundled, zero-dep, seconds): the inline gate that runs on every downloaded candidate. Strongest at *fraud and quality* — hollow implementations, hidden characters, injection phrasing — and it tells you what it didn't scan instead of silently passing it.
- **[NVIDIA SkillSpector](https://github.com/NVIDIA/SkillSpector)** (optional, recommended): the pre-adoption deep pass — 68 patterns/17 categories, YARA signatures, CVE lookups, 0–100 risk score. Strongest at *malice*.

Head-to-head on a malicious fixture, both caught injection/RLO/zero-width; each caught things the other missed. Use both: the fast gate on everything, the deep pass on whatever you're about to adopt. And read `references/trust-and-safety-review.md` for the checks no scanner can make.

## Install

```bash
git clone https://github.com/HWY1dot0/skills.git
ln -s "$(pwd)/skills/skill-selector" ~/.claude/skills/skill-selector
```

Or copy the directory in. Requirements: Python 3.9+ (stdlib only). Optional but recommended: an authenticated `gh` CLI (unlocks GitHub code search — the only lane that searches SKILL.md *content* — and lifts API limits from 60 to 5000/hr), and SkillSpector for deep scans.

Try it:

```bash
python3 scripts/match_local.py "fill pdf form"
python3 scripts/fetch_candidates.py "fill pdf form" "pdf form filler" --limit 5
python3 scripts/trust_scan.py ./candidates/<skill>
```

## Design principles

- **Scripts gather, agents judge.** Everything deterministic (searching, scanning, counting, ranking) is a zero-token Python script; the agent spends tokens only on judgment. That's why light mode costs ~5k, not ~50k.
- **Decide on evidence, not descriptions.** A description is marketing. The trust gate reads code; the run-off executes it; judges are blind and default to *fail*.
- **Fail closed, visibly.** The scanner reports its blind spots; the fetcher labels rate-limited lookups as *unverified* instead of *dead*; an empty search distinguishes "quota exhausted" from "genuinely nothing".
- **Institutional memory.** Every decision appends one line to a git-ignored ledger; the next selection greps it before searching anywhere.

Some code comments are in Chinese (the author works bilingually); user-facing docs are bilingual — see [README.zh-CN.md](README.zh-CN.md).

## License

MIT
