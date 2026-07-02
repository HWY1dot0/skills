#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
match_local.py — Tier-0 匹配:给一个能力描述,把你**已装的** skill 按相关度排出来。

筛选 skill 的第一问往往是"我是不是早就有了"。`inventory_skills.py` 只会**列**;
这个会**按任务匹配**——穷尽 Tier 0(已加载/本地、零成本、预先可信)后,再决定
要不要去全网 `fetch_candidates.py`。纯词法、无 LLM、无网络:用 SKILL.md 的
name+description 算相关度(英文分词 + 中文 bigram + IDF 加权,name 命中加权)。

两种本地形态都算 Tier 0:目录式 skill(含 SKILL.md)和顶层平铺的 command .md
(~/.claude/commands/cpi.md 这类,无 name 字段、名字即文件名)。默认两个目录都扫。

用法
----
    python match_local.py "create data visualization chart"
    python match_local.py "把数据画成图" --dir ~/.claude/skills --top 8
    python match_local.py "fill pdf form" --json

输出:相关度排名 + 每条命中的词 + 一句裁断(reuse / 弱匹配 / 去全网)。
退出码:0=有强匹配(建议先复用)  1=只有弱匹配  2=本地无匹配(去全网)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from pathlib import Path

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)
NAME_BOOST = 2.5          # 命中 name 比命中 description 更强的信号
STRONG = 0.45            # 覆盖率阈值:matched/总查询词 ≥ 此值且分数领先 → 强匹配


def _frontmatter(text: str) -> dict:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}
    block = m.group(1)
    out = {"name": "", "description": ""}
    # description 可能跨多行(> 或 | 块),粗略抓到下一个顶格 key 为止
    for key in ("name", "description"):
        km = re.search(rf"^{key}\s*:\s*(.*?)(?=\n\w[\w-]*\s*:|\Z)", block, re.MULTILINE | re.DOTALL)
        if km:
            out[key] = re.sub(r"\s+", " ", km.group(1)).strip().strip("\"'>|").strip()
    return out


# 中英概念归一:把同义词折成一个规范 token,跨语言/同义才对得上。
# 故意紧凑、只覆盖明确可分的主域;有歧义的(如 word=Word文档 vs 单词)不收。可扩展。
CONCEPTS = {
    "§chart": ["chart", "plot", "figure", "graph", "visuali", "diagram", "可视化", "制图",
               "画图", "出图", "配图", "图表", "作图", "绘图", "折线", "柱状", "散点",
               "热力", "看板", "仪表盘", "sketchnote", "信息图"],
    "§data": ["dataset", "data ", "csv", "excel", "dataframe", "parquet", "数据", "表格", "edb"],
    "§pdf": ["pdf", "docx", "word document", "文档", "公文"],
    "§name": ["english name", "命名", "名字", "英文名", "name analysis"],
    "§news": ["news", "新闻", "简报", "资讯", "headline", "头条"],
    "§research": ["research", "调研", "文献", "综述", "literature", "catch up"],
    "§meeting": ["meeting", "会议", "日历", "calendar", "日程", "邀请"],
    "§transcribe": ["transcript", "转录", "纪要", "专家会", "电话会"],
    "§slides": ["slide", "deck", "presentation", "pptx", "ppt", "幻灯"],
    # 宏观/市场域(本机最高频的任务域,缺了会对主业任务假阴性)
    "§fed": ["fomc", "fed ", "fedspeak", "美联储", "联储", "powell", "鲍威尔", "货币政策",
             "monetary policy", "利率决议", "rate cut", "rate hike", "加息", "降息", "点阵"],
    "§inflation": ["inflation", "cpi", "pce", "通胀", "通缩", "物价", "价格指数", "deflation"],
    "§labor": ["nfp", "payroll", "非农", "就业", "employment", "unemployment", "失业",
               "jobs report", "jolts", "劳动力"],
    "§markets": ["股市", "债市", "行情", "看板", "大类资产", "美股", "港股", "a股",
                 "treasury", "yield", "国债", "收益率", "positioning", "持仓", "cot ",
                 "equity", "sector", "板块"],
    "§geopol": ["iran", "伊朗", "geopolit", "地缘", "制裁", "sanction", "tariff", "关税"],
}


def _tokens(text: str) -> set[str]:
    """英文词(≥3 字母)+ 中文 bigram + 概念归一 token,都小写。"""
    text = text.lower()
    toks = set(re.findall(r"[a-z][a-z0-9+\-]{2,}", text))
    for run in re.findall(r"[一-鿿]{2,}", text):
        toks.update(run[i:i + 2] for i in range(len(run) - 1))
    for one in re.findall(r"(?<![一-鿿])[一-鿿](?![一-鿿])", text):
        toks.add(one)
    for canon, members in CONCEPTS.items():        # 同义概念折成规范 token
        if any(m in text for m in members):
            toks.add(canon)
    return toks


SKIP_DIRS = {"__pycache__", "node_modules", ".git"}


def _walk_skill_mds(root: Path):
    """找 root 下所有 SKILL.md。用 os.walk(followlinks=True) 而非 rglob ——
    rglob 不跟**目录级** symlink,symlink 装的 skill 会整个静默消失(2026-07-03
    dotfiles symlink 化当天就咬过:17 个只见 7 个)。"""
    seen: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
        rp = os.path.realpath(dirpath)
        if rp in seen:                          # symlink 环路保护
            dirnames[:] = []
            continue
        seen.add(rp)
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        if "SKILL.md" in filenames:
            yield Path(dirpath) / "SKILL.md"


def load_skills(dirs: list[Path]) -> list[dict]:
    """目录式 skill(SKILL.md)+ 根目录顶层平铺的 command .md 都收。
    command 无 name 字段 → 名字取文件名;去重按 realpath(symlink 与真身算一个)。"""
    skills = []
    seen = set()
    for root in dirs:
        if not root.exists():
            continue
        cands = [(md, md.parent.name, str(md.parent)) for md in sorted(_walk_skill_mds(root))]
        for md in sorted(root.glob("*.md")):    # 顶层 command;glob 跟随文件级 symlink
            if md.name.upper() in {"SKILL.MD", "README.MD"}:
                continue
            cands.append((md, md.stem, str(md)))
        for md, fallback, path in cands:
            key = os.path.realpath(path)
            if key in seen:
                continue
            seen.add(key)
            fm = _frontmatter(md.read_text(encoding="utf-8", errors="replace"))
            name = fm.get("name") or fallback
            desc = fm.get("description", "")
            skills.append({
                "name": name, "description": desc, "path": path,
                "name_tok": _tokens(name), "text_tok": _tokens(f"{name} {desc}"),
            })
    return skills


def _idf(skills: list[dict]) -> dict:
    n = len(skills) or 1
    df: dict[str, int] = {}
    for s in skills:
        for t in s["text_tok"]:
            df[t] = df.get(t, 0) + 1
    return {t: math.log((n + 1) / (c + 0.5)) for t, c in df.items()}


def rank(query: str, skills: list[dict]) -> list[dict]:
    idf = _idf(skills)
    q = _tokens(query)
    unseen = math.log(len(skills) + 1)
    q_weighted = {t: idf.get(t, unseen) for t in q}              # 未见过的词给高 idf
    # 覆盖率分母只取**最显著的若干查询词**(top-k by idf),避免冗长查询里的噪音 bigram
    # (把数/据画/an…)稀释 —— 它们既不显著也匹配不上,不该计入。
    salient = sorted(q_weighted.values(), reverse=True)[:6]
    denom = sum(salient) or 1.0
    out = []
    for s in skills:
        matched = q & s["text_tok"]
        score = 0.0
        for t in matched:
            score += q_weighted[t] * (NAME_BOOST if t in s["name_tok"] else 1.0)
        coverage = min(1.0, sum(q_weighted[t] for t in matched) / denom)
        out.append({**{k: s[k] for k in ("name", "description", "path")},
                    "score": round(score, 3), "coverage": round(coverage, 3),
                    "matched": sorted(matched)})
    out.sort(key=lambda x: x["score"], reverse=True)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Tier-0 本地 skill 相关度匹配")
    ap.add_argument("query", help="能力描述(动词+名词+格式),中英皆可")
    ap.add_argument("--dir", action="append", default=None,
                    help="skill/command 根目录(可多次);默认 ~/.claude/skills + ~/.claude/commands")
    ap.add_argument("--top", type=int, default=6, help="显示前 N(默认 6)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    dirs = [Path(d).expanduser()
            for d in (args.dir or ["~/.claude/skills", "~/.claude/commands"])]
    skills = load_skills(dirs)
    if not skills:
        print(f"未在 {', '.join(map(str, dirs))} 找到任何 SKILL.md", file=sys.stderr)
        return 2

    ranked = rank(args.query, skills)
    top = [r for r in ranked if r["score"] > 0][: args.top]
    best = top[0] if top else None
    second = top[1] if len(top) > 1 else None
    # 强匹配:覆盖率够高,**或**覆盖率中等但 #1 明显甩开 #2(领先 ≥1.5×)。
    dom = (best["score"] / second["score"]) if (second and second["score"]) else 99.0
    strong = bool(best) and (best["coverage"] >= STRONG or
                             (best["coverage"] >= 0.30 and dom >= 1.5))
    verdict = "reuse" if strong else ("weak" if best else "none")

    if args.json:
        print(json.dumps({"query": args.query, "verdict": verdict, "results": top},
                         ensure_ascii=False, indent=2))
        return {"reuse": 0, "weak": 1, "none": 2}[verdict]

    print(f"==== match_local  «{args.query}»  ({len(skills)} 个本地 skill)====")
    if not top:
        print("  本地无任何词法匹配。")
    width = max((len(r["name"]) for r in top), default=4)
    for i, r in enumerate(top, 1):
        bar = "█" * min(20, int(r["coverage"] * 20 + 0.5))
        print(f"  {i}. {r['name']:<{width}}  cov {r['coverage']:.2f} {bar}")
        print(f"     {'':<{width}}  命中: {' · '.join(r['matched']) or '—'}")
    # 惰性分支:best 可能是 None(verdict=none),不能在 dict 里急切求值 f-string
    if verdict == "reuse":
        tip = f"→ 强匹配:先考虑复用 / fork「{best['name']}」,别急着去全网。"
    elif verdict == "weak":
        tip = (f"→ 只有弱匹配(最高「{best['name']}」cov {best['coverage']:.2f})。"
               f"够近就 fork,否则 fetch_candidates.py 去全网。")
    else:
        tip = "→ 本地无匹配:直接 fetch_candidates.py 去注册表/GitHub 找。"
    print(f"---- {verdict.upper()} ----\n{tip}")
    return {"reuse": 0, "weak": 1, "none": 2}[verdict]


if __name__ == "__main__":
    sys.exit(main())
