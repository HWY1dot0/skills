#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
compare_candidates.py — Step 5 脚手架:把下载好的候选并排成"评测卡"。

"靠跑定胜负"是 skill-selector 最决定性的一步,但脚本跑不了 LLM —— 真正的
"各跑一遍同一个用例"得由 agent 做。这个工具把**所有能确定性测的**先聚好,
让那一步有结构化起点,而不是对着一堆目录干瞪眼:

  · 信任门判定(调 trust_scan):FAIL/WARN/PASS
  · 实质 vs 空壳:真实代码行数 / 函数数 / 空壳命中数(看着像有料还是薄包装)
  · 依赖(requirements.txt)—— 你的环境有没有
  · 自带 examples / tests / evals(可测性)
  · SKILL.md 是否声明了用法/IO

它**不替你做决定**:输出末尾会列出"接下来要跑的事"。一次真跑胜过十次读卡。

用法
----
    python compare_candidates.py <candidates_dir>        # fetch_candidates 的输出目录
    python compare_candidates.py skillA/ skillB/ skillC/  # 直接给若干 skill 目录
    python compare_candidates.py <dir> --json
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import trust_scan as ts  # noqa: E402

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)
EXAMPLE_HINT = re.compile(r"example|test|eval|demo|sample|fixture", re.I)
USAGE_HINT = re.compile(r"^#+\s*(usage|用法|使用|quick\s*start|example)", re.I | re.M)


def _frontmatter(text: str) -> dict:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}
    out = {"name": "", "description": ""}
    for key in ("name", "description"):
        km = re.search(rf"^{key}\s*:\s*(.*?)(?=\n\w[\w-]*\s*:|\Z)", m.group(1), re.M | re.S)
        if km:
            out[key] = re.sub(r"\s+", " ", km.group(1)).strip().strip("\"'>|").strip()
    return out


def _py_metrics(py_files: list[Path]) -> tuple[int, int]:
    """(真实代码行数, 函数数)—— 空行/纯注释不算。"""
    loc = funcs = 0
    for p in py_files:
        try:
            src = p.read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            continue
        for line in src.splitlines():
            s = line.strip()
            if s and not s.startswith("#"):
                loc += 1
        try:
            funcs += sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                         for n in ast.walk(ast.parse(src)))
        except SyntaxError:
            pass
    return loc, funcs


def bench(skill_dir: Path, meta: dict | None) -> dict:
    # walk_files 跟随目录 symlink(rglob 不跟,symlink 装的内容会静默消失)
    files = [p for p in ts.walk_files(skill_dir) if p.is_file()]
    py = [p for p in files if p.suffix == ".py"]
    md = next((p for p in files if p.name == "SKILL.md"), None)
    fm = _frontmatter(md.read_text(encoding="utf-8", errors="replace")) if md else {}

    findings = ts.scan(skill_dir)
    summ = ts.summarize(findings)
    stub = sum(1 for f in findings if f.code in
               {"HARDCODED_RETURN", "EMPTY_FUNC", "STUB_MARKER", "NOT_IMPLEMENTED"})
    loc, nfunc = _py_metrics(py)

    req = skill_dir / "requirements.txt"
    deps = [l.strip() for l in req.read_text(encoding="utf-8", errors="replace").splitlines()
            if l.strip() and not l.strip().startswith("#")] if req.exists() else []

    has_examples = any(EXAMPLE_HINT.search(p.name) or
                       any(EXAMPLE_HINT.fullmatch(part) for part in p.parts) for p in files)
    has_usage = bool(md and USAGE_HINT.search(md.read_text(encoding="utf-8", errors="replace")))

    return {
        "name": fm.get("name") or skill_dir.name,
        "description": fm.get("description", ""),
        "path": str(skill_dir),
        "stars": (meta or {}).get("stars"),
        "provenance": (meta or {}).get("provenance", ""),
        "trust": summ["verdict"], "trust_fail": summ["fail"], "trust_warn": summ["warn"],
        "py_loc": loc, "n_funcs": nfunc, "stub_hits": stub,
        "n_scripts": len(py), "n_refs": sum(1 for p in files if "references" in p.parts),
        "deps": deps, "has_examples": has_examples, "has_usage": has_usage,
        # 粗略"薄包装"信号:几乎没真实代码,或代码里空壳占比高
        "thin": (len(py) > 0 and loc < 40) or (loc > 0 and stub >= max(2, nfunc // 2)),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="并排比较候选 skill(Step 5 脚手架)")
    ap.add_argument("paths", nargs="+", help="一个 candidates 目录,或若干 skill 目录")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    # 解析目标:若给的是 fetch_candidates 的目录(含 candidates.json),展开其子 skill
    skill_dirs: list[tuple[Path, dict | None]] = []
    metas: dict[str, dict] = {}
    for raw in args.paths:
        p = Path(raw).expanduser()
        cj = p / "candidates.json"
        if p.is_dir() and cj.exists():
            for m in json.loads(cj.read_text(encoding="utf-8")):
                if m.get("localPath"):
                    metas[str(Path(m["localPath"]))] = m
            for sub in sorted(p.iterdir()):
                if sub.is_dir() and (sub / "SKILL.md").exists():
                    skill_dirs.append((sub, metas.get(str(sub))))
        elif p.is_dir():
            skill_dirs.append((p, None))

    if not skill_dirs:
        print("未找到可比较的 skill 目录(需含 SKILL.md;或给 fetch_candidates 的输出目录)",
              file=sys.stderr)
        return 1

    cards = [bench(d, m) for d, m in skill_dirs]

    if args.json:
        print(json.dumps(cards, ensure_ascii=False, indent=2))
        return 0

    print(f"==== compare_candidates  ({len(cards)} 个候选)====\n")
    hdr = f"{'name':<24} {'trust':<6} {'★':>6} {'pyLOC':>6} {'fn':>3} {'stub':>4} {'ex':>3} {'deps':>4}"
    print(hdr); print("-" * len(hdr))
    for c in sorted(cards, key=lambda x: (x["trust"] == "FAIL", -(x.get("stars") or 0))):
        star = "?" if c["stars"] is None else c["stars"]
        flag = " ⚠薄" if c["thin"] else ""
        print(f"{c['name'][:24]:<24} {c['trust']:<6} {star:>6} {c['py_loc']:>6} "
              f"{c['n_funcs']:>3} {c['stub_hits']:>4} {'Y' if c['has_examples'] else '-':>3} "
              f"{len(c['deps']):>4}{flag}")
    print()
    for c in cards:
        notes = []
        if c["trust"] == "FAIL":
            notes.append(f"信任门 FAIL×{c['trust_fail']} —— 采用前逐条确认")
        if c["thin"]:
            notes.append("薄/疑空壳(真实代码少或空壳占比高)——别被'有脚本'骗")
        if c["deps"]:
            notes.append(f"依赖 {len(c['deps'])} 个:{', '.join(c['deps'][:4])}{'…' if len(c['deps'])>4 else ''}")
        if not c["has_usage"]:
            notes.append("SKILL.md 未声明用法/IO —— 测起来得自己摸")
        if notes:
            print(f"  • {c['name']}: " + "; ".join(notes))

    print("\n---- 接下来(这步脚本替不了)----")
    print("  1. 用 Step 1 的成功标准,把这几个候选在**同一个测试用例**上各跑一遍。")
    print("  2. 先 correctness(过不过标准),再 consistency(同例跑 2-3 次,飘的淘汰)。")
    print("  3. trust=FAIL 的不进比;⚠薄 的重点验它到底干不干活。")
    print("  4. 把结论记进 Step 6 决策台账(选了谁/为什么/测试结果)。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
