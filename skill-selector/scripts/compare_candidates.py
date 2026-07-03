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

# ── 形态指纹(shape)——渲染器画"结构差异"用的确定性骨架 ────────────────────
# 只读 SKILL.md 得来,本地/远程候选对称(都只需一份 md),但这是**文档结构**
# 不是验证过的执行流;真流程要 /skillviz 下钻。render_compare.py 消费本字段。
HDR_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*$", re.M)
# 编号步骤:关键词+编号,或 1-2 位数字紧跟分隔符(".""))"、"—")。
# 卡死 4 位年份("2024 Progress")和无分隔裸数字("3 Overview"),它们不是流水线步骤。
STEP_RE = re.compile(
    r"^\s*(?:step|phase|part|stage|步骤|步|阶段|环节)\s*\d{1,2}\b"
    r"|^\s*\d{1,2}\s*[.)、:：\-—]", re.I)
FENCE_RE = re.compile(r"```")
CMD_RE = re.compile(
    r"```(?:bash|sh|shell|zsh|console|python|py|js|javascript|ts)\b"
    r"|(?<![\w/])python3?\s|(?<![\w/])bash\s|(?<![\w/])curl\s|(?<![\w/])npm\s"
    r"|(?<![\w/])gh\s|(?:^|\s)scripts/|\b[\w.-]+\.py\b|(?<!\w)--[a-z]{2,}",
    re.I | re.M)
GUARD_RE = re.compile(
    r"pitfall|gotcha|failure\s*mode|caveat|铁律|边界|失败模式|陷阱|注意事项|"
    r"禁止|\bdo not\b|don'?t\b", re.I)


def _shape(md_text: str, n_scripts: int) -> dict:
    """从 SKILL.md 抽结构指纹:分节数、每节 cli/llm 倾向、整体 lean、有无护栏。"""
    m = FRONTMATTER_RE.match(md_text)
    body = md_text[m.end():] if m else md_text
    hdrs = [(len(mm.group(1)), mm.group(2).strip(), mm.start(), mm.end())
            for mm in HDR_RE.finditer(body)]
    has_guards = bool(GUARD_RE.search(body))

    step_hdrs = [h for h in hdrs if STEP_RE.match(h[1])]
    if len(step_hdrs) >= 2:            # 有显式编号步骤 → 是条流水线
        picks, structured = step_hdrs, True
    else:                              # 否则退到 H2(不够再 H3)→ 散文式分节
        h2 = [h for h in hdrs if h[0] == 2]
        h3 = [h for h in hdrs if h[0] == 3]
        picks = h2 if len(h2) >= 2 else (h3 if len(h3) >= 2 else (h2 or h3))
        structured = False

    CAP = 16
    nodes = []
    for lvl, text, hstart, hend in picks:
        nxt = len(body)                # 节体 = 到下一个同级或更浅标题为止(含其子节)
        for l2, _t, s2, _e in hdrs:
            if s2 > hstart and l2 <= lvl:
                nxt = s2
                break
        seg = body[hend:nxt]
        # cli 步的门槛:有围栏代码块,或 ≥3 个命令信号。散文里零星提到命令行工具不算。
        cli = bool(FENCE_RE.search(seg)) or len(CMD_RE.findall(seg)) >= 3
        nodes.append({"title": text[:48], "kind": "cli" if cli else "llm"})
        if len(nodes) >= CAP:
            break

    cli_n = sum(1 for n in nodes if n["kind"] == "cli")
    # lean 纯由指纹条定,和 strip 永远一致;"有脚本"是另一维,交给 has_scripts chip。
    if not nodes:
        lean = "cli" if n_scripts else "llm"
    else:
        frac = cli_n / len(nodes)
        lean = "cli" if frac >= 0.55 else ("llm" if frac <= 0.2 else "mixed")

    return {"structured": structured, "n_nodes": len(picks), "nodes": nodes,
            "truncated": max(0, len(picks) - len(nodes)),  # 指纹条只画前 CAP 个,余数显式标出
            "lean": lean, "has_scripts": bool(n_scripts), "has_guards": has_guards}


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
    md_text = md.read_text(encoding="utf-8", errors="replace") if md else ""
    fm = _frontmatter(md_text)

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
    has_usage = bool(USAGE_HINT.search(md_text))

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
        "shape": _shape(md_text, len(py)),  # 结构指纹(render_compare.py 消费)
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
