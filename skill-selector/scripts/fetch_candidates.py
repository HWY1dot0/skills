#!/usr/bin/env python3
"""
fetch_candidates.py — Discover and download skill candidates from public registries.

This is the automation behind Step 2 (Collect candidates). Given a *capability*
query, it searches public skill registries, dedupes the hits, and downloads each
candidate's full skill directory (SKILL.md + references/ + scripts/) into a local
sandbox you can then read, score, and run through the rest of the workflow.

Sources, in order of practical reliability (verified live, 2026-07):
  - GitHub code search (STRONGEST, needs gh CLI auth) — searches SKILL.md file
                            CONTENT, not just name/description. Auto-enabled when
                            `gh auth status` passes; 10 req/min. --no-gh to skip.
  - SkillsMP   (PRIMARY registry) — anonymous REST, 50/day + 10/min (self-reported
                            via x-ratelimit headers). Search is LEXICAL: run 2-3
                            query variants phrased like skill names and let this
                            script union them. Repo-level stars flood rankings
                            (benchmark monorepos) — collapsed to 2 per repo here.
  - agentskill.work (SECONDARY) — anonymous JSON, repo-level index, every item
                            carries canonical GitHub URL + stars + quality_score.
                            Strict lexical AND: multi-word queries often return 0,
                            so this script retries per-keyword automatically.
  - VoltAgent  (optional) — curated awesome-list README on GitHub; parsed for
                            repo links matching the query. Use --include-voltagent.
  - skills.sh  (GATED)    — still requires a Vercel OIDC token (rechecked 2026-07).
                            Not wired in.

No source does semantic search (verified: 3 phrasings of one capability shared
ZERO results on SkillsMP) — so relevance is enforced client-side: candidates are
re-ranked by query-token coverage before the star sort, and AGAIN on SKILL.md
full text after download (descriptions are marketing; full text is evidence).

Downloading uses the GitHub Contents API (unauthenticated: 60 req/hr). Set
GITHUB_TOKEN in the environment to raise that limit if you fetch many candidates.

Usage:
    python fetch_candidates.py "fill pdf form fields" --limit 5 --out /tmp/candidates
    python fetch_candidates.py "extract tables xlsx" --sort stars --include-voltagent
    python fetch_candidates.py "slide deck from outline" --no-download   # list only

Output:
  - A printed ranked table of candidates.
  - <out>/<author>__<name>/...   one folder per downloaded candidate.
  - <out>/candidates.json        metadata + local paths, ready for inventory_skills.py.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

SKILLSMP_SEARCH = "https://skillsmp.com/api/v1/skills/search"
AGENTSKILLWORK_API = "https://agentskill.work/api/skills"
VOLTAGENT_README = "https://raw.githubusercontent.com/VoltAgent/awesome-agent-skills/main/README.md"
GITHUB_API = "https://api.github.com"

UA = "skill-selector-fetch/1.0"


def _get(url: str, headers: dict | None = None, timeout: int = 25) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _get_json(url: str, headers: dict | None = None, timeout: int = 25):
    return json.loads(_get(url, headers, timeout).decode("utf-8", "replace"))


# ---------------------------------------------------------------- sources

_QUOTA_PRINTED = False


def search_skillsmp(query: str, limit: int, sort: str) -> list[dict]:
    """Primary registry. Anonymous SkillsMP REST API. Returns normalized candidates.

    Lexical search — callers should pass several query variants (this script's
    positional args) and let dedupe/union do the recall work. Quota: 50/day +
    10/min, self-reported in x-ratelimit-* headers (printed once per run)."""
    global _QUOTA_PRINTED
    params = urllib.parse.urlencode({"q": query, "limit": min(limit, 50), "sortBy": sort})
    req = urllib.request.Request(f"{SKILLSMP_SEARCH}?{params}", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            payload = json.loads(r.read().decode("utf-8", "replace"))
            if not _QUOTA_PRINTED:
                day = r.headers.get("x-ratelimit-daily-remaining")
                minute = r.headers.get("x-ratelimit-minute-remaining")
                if day is not None:
                    print(f"  (SkillsMP 配额:今日剩 {day}/50,本分钟剩 {minute}/10)", file=sys.stderr)
                _QUOTA_PRINTED = True
    except urllib.error.HTTPError as e:
        hint = " —— 429/403 是配额不是没结果" if e.code in (403, 429) else ""
        print(f"  ! SkillsMP HTTP {e.code} ({e.reason}){hint} — skipping source", file=sys.stderr)
        return []
    except Exception as e:  # noqa: BLE001
        print(f"  ! SkillsMP unreachable: {e} — skipping source", file=sys.stderr)
        return []

    skills = (payload.get("data") or {}).get("skills") or []
    out = []
    for s in skills:
        out.append(
            {
                "name": s.get("name", ""),
                "author": s.get("author", ""),
                "description": (s.get("description") or "").strip().strip('"'),
                "githubUrl": s.get("githubUrl", ""),
                "stars": s.get("stars", 0),
                "updatedAt": s.get("updatedAt"),   # unix epoch str — 唯一的新鲜度信号
                "source": "skillsmp",
            }
        )
    return out


def _gh_available() -> bool:
    try:
        r = subprocess.run(["gh", "auth", "status"], capture_output=True, timeout=10)
        return r.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def search_gh_code(query: str, limit: int) -> list[dict]:
    """GitHub code search via authed gh CLI — the strongest lane: it matches
    SKILL.md file CONTENT, where registries only match name/description.
    Budget: code_search bucket is 10 req/min; one call per query variant."""
    try:
        r = subprocess.run(
            ["gh", "search", "code", "--filename", "SKILL.md", query,
             "--limit", str(min(limit * 4, 30)), "--json", "repository,path"],
            capture_output=True, text=True, timeout=45)
        if r.returncode != 0:
            print(f"  ! gh code search: {r.stderr.strip()[:120]} — skipping", file=sys.stderr)
            return []
        items = json.loads(r.stdout or "[]")
    except Exception as e:  # noqa: BLE001
        print(f"  ! gh code search: {e} — skipping", file=sys.stderr)
        return []
    out = []
    for it in items:
        path = it.get("path", "")
        if not path.endswith("SKILL.md"):
            continue
        repo = it.get("repository") or {}
        full = repo.get("nameWithOwner") or repo.get("fullName") or ""
        if not full and repo.get("url"):
            m = re.search(r"github\.com/([^/]+/[^/]+)", repo["url"])
            full = m.group(1) if m else ""
        if not full:
            continue
        skill_dir = path[: -len("SKILL.md")].rstrip("/")
        name = skill_dir.split("/")[-1] if skill_dir else full.split("/")[-1]
        out.append({
            "name": name, "author": full.split("/")[0],
            "description": "",           # code search 不带 description;下载后全文 rerank 兜底
            "githubUrl": f"https://github.com/{full}" + (f"/tree/HEAD/{skill_dir}" if skill_dir else ""),
            "stars": None,               # canonicalize 阶段读真星
            "source": "gh-code",
        })
    return out


def _asw_text(v) -> str:
    """agentskill.work 的 summary/description 可能是 {en,zh} 对象。"""
    if isinstance(v, dict):
        return str(v.get("en") or v.get("zh") or "")
    return str(v or "")


def search_agentskillwork(query: str, limit: int) -> list[dict]:
    """Secondary registry: anonymous JSON, repo-level, canonical GitHub URL on
    every item. Strict lexical AND (multi-word query often → total 0), so fall
    back to per-keyword probes automatically."""
    def _q(q: str) -> list[dict]:
        params = urllib.parse.urlencode({"q": q, "limit": min(limit * 2, 20)})
        try:
            payload = _get_json(f"{AGENTSKILLWORK_API}?{params}")
            return payload.get("items") or []
        except Exception as e:  # noqa: BLE001
            print(f"  ! agentskill.work: {e} — skipping", file=sys.stderr)
            return []

    items = _q(query)
    if not items:                        # 多词 AND 打空 → 逐关键词
        for kw in [w for w in re.split(r"\W+", query) if len(w) > 3][:3]:
            items += _q(kw)
    out, seen = [], set()
    for it in items:
        full = it.get("full_name", "")
        if not full or full in seen:
            continue
        seen.add(full)
        out.append({
            "name": it.get("name") or full.split("/")[-1],
            "author": full.split("/")[0],
            "description": (_asw_text(it.get("summary")) or _asw_text(it.get("description")))[:300],
            "githubUrl": it.get("html_url", ""),
            "stars": it.get("stars"),
            "source": "agentskill.work",
        })
    return out[: limit * 2]


def search_voltagent(query: str) -> list[dict]:
    """Optional source. Parse the awesome-list README for entries matching the query.

    README lines look like:  **[owner/name]** - description  (with a markdown link).
    We keep entries whose name or description contains any query token.
    """
    try:
        text = _get(VOLTAGENT_README).decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        print(f"  ! VoltAgent README unreachable: {e} — skipping source", file=sys.stderr)
        return []

    tokens = [t for t in re.split(r"\W+", query.lower()) if len(t) > 2]
    # Entry pattern: **[label](url)** - description   OR   **[label]** - description
    entry_re = re.compile(r"\*\*\[([^\]]+)\]\(([^)]+)\)\*\*\s*[-–—]\s*(.+)")
    out = []
    for line in text.splitlines():
        m = entry_re.search(line)
        if not m:
            continue
        label, url, desc = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
        hay = f"{label} {desc}".lower()
        if tokens and not any(t in hay for t in tokens):
            continue
        if "github.com" not in url:
            continue
        name = label.split("/")[-1]
        author = label.split("/")[0] if "/" in label else ""
        out.append(
            {
                "name": name,
                "author": author,
                "description": desc,
                "githubUrl": url,
                "stars": None,
                "source": "voltagent",
            }
        )
    return out


# ---------------------------------------------------------------- dedup

def _norm_key(c: dict) -> str:
    """Dedup key: normalized owner/repo/path from the GitHub URL, else author/name."""
    url = (c.get("githubUrl") or "").lower().rstrip("/")
    m = re.search(r"github\.com/([^/]+)/([^/]+)(?:/tree/[^/]+/(.*))?", url)
    if m:
        owner, repo, path = m.group(1), m.group(2), (m.group(3) or "")
        return f"{owner}/{repo}/{path}".rstrip("/")
    return f"{c.get('author','')}/{c.get('name','')}".lower()


def dedupe(candidates: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for c in candidates:
        k = _norm_key(c)
        if k not in seen:
            seen[k] = c
        else:
            # Prefer the entry that carries a star count (richer provenance).
            if seen[k].get("stars") is None and c.get("stars") is not None:
                seen[k] = c
    return list(seen.values())


def collapse_repo_floods(candidates: list[dict], cap: int = 2) -> list[dict]:
    """Registry stars are REPO-level: a benchmark monorepo (e.g. SkillLearnBench)
    contributes hundreds of machine-generated near-duplicate skills all carrying
    the same inflated star count, flooding the top-N. Keep at most `cap` per repo
    (input order preserved, so the best-ranked survive)."""
    count: dict[str, int] = {}
    out = []
    for c in candidates:
        m = re.search(r"github\.com/([^/]+/[^/]+)", (c.get("githubUrl") or "").lower())
        key = m.group(1) if m else (c.get("author") or "?").lower()
        if count.get(key, 0) >= cap:
            continue
        count[key] = count.get(key, 0) + 1
        out.append(c)
    return out


# ------------------------------------------------------------ relevance rerank
# No source does semantic search (verified 2026-07: three phrasings of one
# capability → zero shared results on SkillsMP). Registry order is popularity,
# not fit — so rank by query-token coverage first, stars second; and re-rank on
# SKILL.md FULL TEXT after download (descriptions are marketing).

def _tok(text: str) -> set[str]:
    text = text.lower()
    toks = set(re.findall(r"[a-z][a-z0-9+\-]{2,}", text))
    for run in re.findall(r"[一-鿿]{2,}", text):
        toks.update(run[i:i + 2] for i in range(len(run) - 1))
    return toks


def _relevance(q_toks: set[str], text: str) -> float:
    """查询词覆盖率 0-1。朴素但稳:命中的查询词越多越相关。"""
    if not q_toks:
        return 0.0
    t = _tok(text)
    return sum(1 for x in q_toks if x in t) / len(q_toks)


def rank_key(c: dict):
    """rel 降序 → 有星优先 → 星降序。"""
    return (-(c.get("rel_full") if c.get("rel_full") is not None else c.get("rel") or 0),
            c.get("stars") is None, -(c.get("stars") or 0))


def rerank_by_fulltext(candidates: list[dict], q_toks: set[str]) -> None:
    """下载后用 SKILL.md 全文重算相关度(gh-code 源没有 description,全靠这步)。"""
    for c in candidates:
        lp = c.get("localPath")
        if not lp:
            continue
        smd = None
        for dirpath, _dirs, files in os.walk(lp):
            if "SKILL.md" in files:
                smd = os.path.join(dirpath, "SKILL.md")
                break
        if smd:
            try:
                with open(smd, encoding="utf-8", errors="replace") as f:
                    c["rel_full"] = round(_relevance(q_toks, f.read()), 3)
            except Exception:  # noqa: BLE001
                pass
    candidates.sort(key=rank_key)


# ---------------------------------------------------------------- download

def _parse_gh(url: str):
    """github.com/OWNER/REPO[/tree/BRANCH/PATH] -> (owner, repo, branch, path)."""
    m = re.search(r"github\.com/([^/]+)/([^/]+?)(?:\.git)?(?:/tree/([^/]+)/(.*))?$", url.rstrip("/"))
    if not m:
        return None
    return m.group(1), m.group(2), (m.group(3) or "HEAD"), (m.group(4) or "")


_GH_TOKEN_CACHE: list = []          # [token_or_None],惰性求值一次


def _gh_headers() -> dict:
    h = {"Accept": "application/vnd.github+json"}
    if not _GH_TOKEN_CACHE:
        tok = os.environ.get("GITHUB_TOKEN")
        if not tok:                  # 环境变量没设时借 gh CLI 的登录态(60/hr → 5000/hr)
            try:
                r = subprocess.run(["gh", "auth", "token"], capture_output=True,
                                   text=True, timeout=10)
                tok = r.stdout.strip() if r.returncode == 0 else None
            except Exception:  # noqa: BLE001
                tok = None
        _GH_TOKEN_CACHE.append(tok)
    if _GH_TOKEN_CACHE[0]:
        h["Authorization"] = f"Bearer {_GH_TOKEN_CACHE[0]}"
    return h


# GitHub API rate-limit tracking. Unauthenticated quota is 60 req/hr and each
# canonicalize() burns 2-7 calls, so a default run CAN exhaust it mid-batch.
# Without this flag a 403 looks identical to a 404 and dead-alive provenance
# labels get silently poisoned ("rate-limited" mislabeled as "dead-404").
_RATE_LIMITED = False


def _gh_json(url: str):
    """GitHub API GET that records rate-limiting instead of conflating it with 404."""
    global _RATE_LIMITED
    try:
        return _get_json(url, headers=_gh_headers())
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            _RATE_LIMITED = True
        raise


def download_skill_dir(candidate: dict, out_root: str) -> str | None:
    """Download a candidate's skill directory tree into out_root/<author>__<name>/.

    Walks the GitHub Contents API, recursing into subdirs (references/, scripts/),
    capped so a mis-pointed URL can't pull a whole monorepo.
    """
    parsed = _parse_gh(candidate.get("githubUrl", ""))
    if not parsed:
        print(f"  ! {candidate.get('name')}: unparseable GitHub URL — skipped", file=sys.stderr)
        return None
    owner, repo, branch, path = parsed

    safe = re.sub(r"[^\w.-]+", "-", f"{candidate.get('author','')}__{candidate.get('name','')}").strip("-")
    dest = os.path.join(out_root, safe or f"{owner}-{repo}")
    n = 2                                # 同 repo 同名 skill(路径不同)不能互相覆盖
    while os.path.exists(dest):
        dest = os.path.join(out_root, f"{safe}-{n}")
        n += 1

    files_written = [0]
    MAX_FILES = 40

    def walk(api_path: str, local_dir: str):
        if files_written[0] >= MAX_FILES:
            return
        url = f"{GITHUB_API}/repos/{owner}/{repo}/contents/{urllib.parse.quote(api_path)}?ref={branch}"
        try:
            items = _gh_json(url)
        except urllib.error.HTTPError as e:
            print(f"  ! {owner}/{repo}/{api_path}: GitHub {e.code} — skipped", file=sys.stderr)
            return
        except Exception as e:  # noqa: BLE001
            print(f"  ! {owner}/{repo}/{api_path}: {e} — skipped", file=sys.stderr)
            return
        if isinstance(items, dict):  # a single file was addressed directly
            items = [items]
        for it in items:
            if files_written[0] >= MAX_FILES:
                return
            if it.get("type") == "dir":
                walk(it["path"], os.path.join(local_dir, it["name"]))
            elif it.get("type") == "file" and it.get("download_url"):
                if (it.get("size") or 0) > 1_000_000:   # 单文件 1MB 上限(MAX_FILES 防数量,这里防体积)
                    print(f"  ! {it['path']}: {it['size'] // 1024}KB > 1MB cap — skipped",
                          file=sys.stderr)
                    continue
                try:
                    blob = _get(it["download_url"])
                except Exception as e:  # noqa: BLE001
                    print(f"  ! {it['path']}: download failed ({e})", file=sys.stderr)
                    continue
                os.makedirs(local_dir, exist_ok=True)
                with open(os.path.join(local_dir, it["name"]), "wb") as f:
                    f.write(blob)
                files_written[0] += 1

    walk(path, dest)
    if files_written[0] == 0:
        return None
    return dest


# ------------------------------------------------ provenance / canonicalize
# Registries are LEADS, not truth. Their star count is often that of a vendored
# copy buried in someone else's monorepo (★0) — not the author's repo (★732) —
# and the pointed path is sometimes already 404. So resolve every lead to the
# canonical GitHub source: real stars, live path, author's own repo.

def _repo_meta(owner: str, repo: str) -> dict:
    try:
        d = _gh_json(f"{GITHUB_API}/repos/{owner}/{repo}")
        return {"stars": d.get("stargazers_count", 0), "exists": True,
                "default_branch": d.get("default_branch", "HEAD")}
    except Exception:  # noqa: BLE001
        return {"stars": None, "exists": False, "default_branch": "HEAD"}


def _has_skill_md(owner: str, repo: str, branch: str, path: str) -> bool:
    """True if a SKILL.md sits directly under `path` (repo root if empty)."""
    url = f"{GITHUB_API}/repos/{owner}/{repo}/contents/{urllib.parse.quote(path)}".rstrip("/")
    if branch and branch != "HEAD":
        url += f"?ref={branch}"
    try:
        items = _gh_json(url)
        if isinstance(items, dict):
            return items.get("name", "").upper() == "SKILL.MD"
        return any(it.get("name", "").upper() == "SKILL.MD" for it in items)
    except Exception:  # noqa: BLE001
        return False


def _locate_skill(owner: str, repo: str, branch: str, skill: str) -> str | None:
    for p in ("", f"skills/{skill}", skill, f"src/skills/{skill}", f".claude/skills/{skill}"):
        if _has_skill_md(owner, repo, branch, p):
            return p
    return None


def _search_repos(skill: str) -> list[dict]:
    """GitHub repo search (name + description + topics), highest real-star first.

    Broad on purpose: the canonical source is often a multi-skill repo whose NAME
    differs from the skill (e.g. skill 'nature-figure' lives in 'nature-skills'),
    so an `in:name` search would miss it. Star-sorted so the authoritative repo
    surfaces near the top; _locate_skill then verifies the skill actually lives there.
    """
    q = urllib.parse.quote(skill)
    try:
        d = _gh_json(f"{GITHUB_API}/search/repositories?q={q}&sort=stars&order=desc&per_page=10")
        return d.get("items", [])
    except Exception:  # noqa: BLE001
        return []


def canonicalize(c: dict) -> dict:
    """Resolve a registry lead to its canonical GitHub source; record provenance.

    Degrades gracefully: any network/rate-limit failure leaves the registry data
    intact (just less verified). Sets c['provenance'] and corrects c['stars'].
    """
    parsed = _parse_gh(c.get("githubUrl", ""))
    if not parsed:
        c["provenance"] = "unparseable"
        return c
    owner, repo, branch, path = parsed
    skill = c.get("name", "")
    meta = _repo_meta(owner, repo)
    if not meta["exists"] and _RATE_LIMITED:
        # 403/429 ≠ 404:配额耗尽时不能把 repo 判死,更不能再烧 search API 找"替代源"。
        # 保留 registry 原始数据,标注未验证,让下游知道该打折。
        c["provenance"] = "unverified (github rate-limited — 设 GITHUB_TOKEN 重跑)"
        return c
    ref = meta["default_branch"] if branch == "HEAD" else branch
    path_alive = meta["exists"] and _has_skill_md(owner, repo, ref, path)
    # Vendored signal: skill name absent from repo name AND buried in a subpath
    # (e.g. SkillsMP pointing at someone/monorepo/.../skills/<skill>).
    vendored = skill.lower() not in repo.lower() and path.count("/") >= 1

    if not path_alive or vendored:
        cur = meta["stars"] or 0
        for item in _search_repos(skill):           # star-descending
            o2, r2 = item["full_name"].split("/", 1)
            if o2 == owner and r2 == repo:
                continue
            st2 = item.get("stargazers_count", 0)
            # Results are star-sorted; once we drop to/below the current repo's real
            # stars there's nothing better left to find (unless the current path is
            # dead, in which case any live source beats a 404).
            if st2 <= cur and path_alive:
                break
            loc = _locate_skill(o2, r2, item.get("default_branch", "HEAD"), skill)
            if loc is None:
                continue
            br2 = item.get("default_branch", "HEAD")
            c["githubUrl"] = f"https://github.com/{o2}/{r2}" + (f"/tree/{br2}/{loc}" if loc else "")
            c["author"] = o2
            c["stars"] = st2
            c["source"] = "github-canonical"
            c["provenance"] = "vendored→canonical" if vendored else "dead→canonical"
            time.sleep(0.4)
            return c
        if not path_alive:
            # 中途爆配额时 _has_skill_md/_search_repos 的 False/空是"没查成",不是"没有"
            c["provenance"] = ("unverified (rate-limited mid-resolve)" if _RATE_LIMITED
                               else "dead-404 (no live source found)")
        else:
            c["provenance"] = "github-verified (real ★, best found)"
        if meta["exists"]:
            c["stars"] = meta["stars"]
        time.sleep(0.4)
        return c

    # The pointed repo is itself the source; just correct the (often wrong) star count.
    if meta["exists"]:
        c["stars"] = meta["stars"]
    c["provenance"] = "registry-verified"
    time.sleep(0.2)
    return c


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description="Discover & download skill candidates from registries.")
    ap.add_argument("query", nargs="+",
                    help="One or more queries, run together and merged. Mix a CAPABILITY phrase "
                         "with any KNOWN NAMEs — capability search alone buries proper-noun skills "
                         "(we lost 'nature-figure' that way). e.g. \"fill pdf form\" pdfplumber")
    ap.add_argument("--limit", type=int, default=5, help="Max candidates to keep (default 5)")
    ap.add_argument("--sort", choices=["stars", "recent"], default="stars", help="SkillsMP sort (default stars)")
    ap.add_argument("--out", default="./candidates", help="Sandbox output dir (default ./candidates)")
    ap.add_argument("--include-voltagent", action="store_true", help="Also parse VoltAgent awesome-list")
    ap.add_argument("--no-gh", action="store_true",
                    help="Skip GitHub code search even if gh CLI is authenticated")
    ap.add_argument("--no-download", action="store_true", help="List candidates only; do not download files")
    ap.add_argument("--no-canonical", action="store_true",
                    help="Skip GitHub canonical-source resolution (offline/speed; trusts registry data)")
    args = ap.parse_args()

    queries = args.query
    print(f"Searching sources for: {', '.join(map(repr, queries))}\n")

    gh_ok = (not args.no_gh) and _gh_available()
    if not args.no_gh and not gh_ok:
        print("  (gh CLI 未认证:跳过 GitHub code search —— 唯一能搜 SKILL.md 正文的源。"
              "gh auth login 可解锁)", file=sys.stderr)

    pool: list[dict] = []
    for q in queries:                       # dual/multi-search: capability + known names
        pool += search_skillsmp(q, args.limit * 3, args.sort)
        pool += search_agentskillwork(q, args.limit)
        if gh_ok:
            pool += search_gh_code(q, args.limit)
        if args.include_voltagent:
            pool += search_voltagent(q)

    if not pool:
        print("No candidates found in any source. If an HTTP 403/429 was printed above, that's "
              "a QUOTA problem, not a true null — retry later before concluding anything. "
              "A clean null result points to BUILD (Step 4) — use the closest near-miss as a template.")
        return 0

    candidates = dedupe(pool)
    # Rank: query-relevance FIRST (all sources are lexical; registry order is
    # popularity not fit), stars second. gh-code hits matched on file CONTENT,
    # so their missing description gets a floor instead of a zero. Then collapse
    # repo floods, bound the working set, canonicalize, and re-rank by real data.
    q_toks = set().union(*[_tok(q) for q in queries]) if queries else set()
    for c in candidates:
        c["rel"] = round(_relevance(q_toks, f"{c['name']} {c['description']}"), 3)
        if c["source"] == "gh-code":
            c["rel"] = max(c["rel"], 0.5)
    candidates.sort(key=rank_key)
    candidates = collapse_repo_floods(candidates)
    working = candidates[: max(args.limit * 2, args.limit)]
    if not args.no_canonical:
        print("Resolving leads to canonical GitHub source (real stars + live path) ...",
              file=sys.stderr)
        for c in working:
            canonicalize(c)
        working.sort(key=rank_key)
    candidates = working[: args.limit]

    print(f"Found {len(candidates)} candidate(s) after dedup + flood-collapse + canonical resolution:\n")
    width = max((len(c["name"]) for c in candidates), default=4)
    for i, c in enumerate(candidates, 1):
        stars = "?" if c.get("stars") is None else c["stars"]
        prov = c.get("provenance", "")
        tag = f"{c['source']}{' · ' + prov if prov else ''}"
        desc = c["description"].replace("\n", " ")
        if len(desc) > 90:
            desc = desc[:87] + "..."
        print(f"  {i}. {c['name']:<{width}}  [rel {c.get('rel', 0):.2f}, ★{stars}, {tag}]  {desc}")
        print(f"     {'':<{width}}  ↳ {c['githubUrl']}")

    if not args.no_download:
        os.makedirs(args.out, exist_ok=True)
        print(f"\nDownloading skill directories into {args.out}/ ...")
        for c in candidates:
            dest = download_skill_dir(c, args.out)
            c["localPath"] = dest
            status = dest if dest else "FAILED (no files)"
            print(f"  • {c['name']:<{width}} -> {status}")
            time.sleep(0.3)  # be polite to the GitHub API

        # 全文重排:description 是营销,SKILL.md 全文才见真章(gh-code 源全靠这步)
        rerank_by_fulltext(candidates, q_toks)
        print("\nFinal ranking (SKILL.md full-text relevance):")
        for i, c in enumerate(candidates, 1):
            rf = c.get("rel_full")
            print(f"  {i}. {c['name']:<{width}}  relFull {rf if rf is not None else '—'}"
                  f"  ★{'?' if c.get('stars') is None else c['stars']}")

        manifest = os.path.join(args.out, "candidates.json")
        with open(manifest, "w", encoding="utf-8") as f:
            json.dump(candidates, f, indent=2, ensure_ascii=False)
        print(f"\nWrote {manifest}")
        if _RATE_LIMITED:
            print("\n⚠ GitHub API rate limit was hit during this run: 'unverified' provenance "
                  "labels and any skipped downloads are quota artifacts, not verdicts. "
                  "Set GITHUB_TOKEN (raises 60 → 5000 req/hr) and re-run to fully resolve.")
        print("Next: trust-gate each download →  trust_scan.py", args.out + "/<skill>",
              "(flags danger/injection/stub); then inventory_skills.py", args.out,
              "and compare by running — see references/comparing-effectiveness.md")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
