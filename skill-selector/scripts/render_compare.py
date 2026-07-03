#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
render_compare.py — skill-selector 的"结构对比"渲染器。

把 compare_candidates.py 攒下的确定性评测卡(--json)画成一张单文件 HTML:
横比矩阵(信任门/成色/依赖/示例)+ 每个候选一条**形态指纹**(读 SKILL.md 得来的
分节骨架,红=命令步/灰=模型步),让"不同 skill 结构差异"一眼可见;点任一候选
可下钻到它完整的 skillviz 流程图(若已 /skillviz 生成过)。

分工同 skillviz:数据由 compare_candidates(确定性提取)产,本脚本只做渲染。
视觉语言复用 render_flow.py —— 红=cli 步、灰=llm 步、BOCI mono 红+中性灰。

用法
----
    # A. 吃 compare_candidates 的 JSON
    python compare_candidates.py <dirs...> --json > cards.json
    python render_compare.py cards.json --open

    # B. 直接给 skill 目录 / fetch_candidates 输出目录(内部调 compare_candidates)
    python render_compare.py ~/.claude/skills/audit ~/.claude/skills/learn --open
    python render_compare.py <candidates_dir> -o ~/Coding/Tools/skillviz/out/skill-compare.html
"""
from __future__ import annotations

import argparse
import datetime
import html
import json
import os
import subprocess
import sys
from pathlib import Path
from string import Template

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLVIZ_OUT = os.path.expanduser("~/Coding/Tools/skillviz/out")  # 下钻流程图所在

# BOCI mono 红 + 中性灰(与 render_flow.py / ~/Coding/charts/palettes.py 同源)
C = {
    "red": "#7E2E33", "red_mid": "#BE6B6F", "red_pale": "#EFD8D9",
    "gray_dark": "#4B5563", "gray_mid": "#9CA3AF", "gray_light": "#E5E7EB",
    "ink": "#1F2328", "paper": "#FFFFFF", "panel": "#F7F7F5",
}
KIND_LABEL = {"cli": "CLI", "llm": "LLM", "mixed": "CLI+LLM"}


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


# ── 载入评测卡 ──────────────────────────────────────────────────────────

def load_cards(paths: list[str]) -> list[dict]:
    """`-`/stdin 或单个 .json 文件 → 直接读卡;否则当 skill/候选目录,调 compare_candidates。"""
    if len(paths) == 1 and paths[0] in ("-", "/dev/stdin"):
        cards = json.load(sys.stdin)
        if not isinstance(cards, list):
            sys.exit("stdin: 期望 compare_candidates --json 的卡片数组")
        return cards
    if len(paths) == 1 and paths[0].endswith(".json") and os.path.isfile(paths[0]):
        with open(paths[0], encoding="utf-8") as f:
            cards = json.load(f)
        if not isinstance(cards, list):
            sys.exit(f"{paths[0]}: 期望 compare_candidates --json 的卡片数组")
        return cards
    # 目录模式:复用 compare_candidates 的解析 + bench
    sys.path.insert(0, HERE)
    try:
        import compare_candidates as cc
    except Exception as e:  # noqa: BLE001
        sys.exit(f"无法导入 compare_candidates(需与本脚本同目录):{e}")
    skill_dirs: list[tuple[Path, dict | None]] = []
    for raw in paths:
        p = Path(raw).expanduser()
        cj = p / "candidates.json"
        if p.is_dir() and cj.exists():
            metas = {}
            for m in json.loads(cj.read_text(encoding="utf-8")):
                if m.get("localPath"):
                    metas[str(Path(m["localPath"]))] = m
            for sub in sorted(p.iterdir()):
                if sub.is_dir() and (sub / "SKILL.md").exists():
                    skill_dirs.append((sub, metas.get(str(sub))))
        elif p.is_dir() and (p / "SKILL.md").exists():
            skill_dirs.append((p, None))
        elif p.is_dir():
            skill_dirs.append((p, None))
        else:
            print(f"warn: 跳过(非目录/无 SKILL.md):{raw}", file=sys.stderr)
    if not skill_dirs:
        sys.exit("未找到可比较的 skill 目录(需含 SKILL.md,或给 fetch_candidates 输出目录)")
    return [cc.bench(d, m) for d, m in skill_dirs]


# ── 下钻:找该候选的 skillviz 流程图 ─────────────────────────────────────

def drilldown_href(card: dict) -> str | None:
    base = os.path.realpath(SKILLVIZ_OUT)
    slug = os.path.basename(card.get("path", "").rstrip("/")) or card.get("name", "")
    for cand in {slug, card.get("name", ""), (card.get("name") or "").lower().replace(" ", "-")}:
        if not cand:
            continue
        html_path = os.path.realpath(os.path.join(SKILLVIZ_OUT, f"{cand}.html"))
        # 容器化:解析后必须是 out/ 的直接子文件,挡住候选名里的 ../ 穿越
        if os.path.dirname(html_path) == base and os.path.isfile(html_path):
            return "file://" + html_path
    return None


def skillviz_slug(card: dict) -> str:
    return os.path.basename(card.get("path", "").rstrip("/")) or card.get("name", "skill")


# ── HTML 片段 ───────────────────────────────────────────────────────────

def trust_badge(verdict: str, fail: int, warn: int) -> str:
    # 信任门用墨/灰权重,不占红(红留给 cli 指纹,避免一页两种红义)
    v = verdict or "?"
    cls = {"FAIL": "tr-fail", "WARN": "tr-warn", "PASS": "tr-pass"}.get(v, "tr-warn")
    icon = {"FAIL": "✕", "WARN": "!", "PASS": "✓"}.get(v, "?")
    extra = ""
    if v == "FAIL" and fail:
        extra = f" ×{fail}"
    elif v == "WARN" and warn:
        extra = f" ×{warn}"
    return f'<span class="trust {cls}">{icon} {esc(v)}{esc(extra)}</span>'


def fingerprint(card: dict) -> str:
    s = card.get("shape") or {}
    nodes = s.get("nodes", [])
    if not nodes:
        strip = '<span class="seg seg-none">散文,无显式分节</span>'
    else:
        segs = []
        for i, n in enumerate(nodes, 1):
            k = n.get("kind", "llm")
            segs.append(f'<span class="seg seg-{esc(k)}" title="{esc(n.get("title",""))}">'
                        f'{i}</span>')
        strip = '<span class="seg-sep">·</span>'.join(segs)
        trunc = s.get("truncated", 0)
        if trunc:                       # 指纹条封顶后剩余节数显式标出,不静默截断
            strip += (f'<span class="seg-sep">·</span>'
                      f'<span class="seg seg-more" title="还有 {esc(trunc)} 节未画">+{esc(trunc)}</span>')
    lean = s.get("lean", "llm")
    kind_txt = KIND_LABEL.get(lean, lean)
    kicker = ("编号流水线" if s.get("structured") else "散文式") + f" · {s.get('n_nodes', 0)} 节 · {esc(kind_txt)}"
    return f'<div class="fp">{strip}</div><div class="fp-label">▸ {esc(kicker)}</div>'


def chips(card: dict) -> str:
    s = card.get("shape") or {}
    out = []
    out.append('<span class="chip">编号流水线</span>' if s.get("structured")
               else '<span class="chip chip-mut">散文式</span>')
    if s.get("has_scripts") and card.get("n_scripts"):
        out.append(f'<span class="chip">脚本 {esc(card["n_scripts"])}</span>')
    if card.get("n_refs"):
        out.append(f'<span class="chip">参考 {esc(card["n_refs"])}</span>')
    if s.get("has_guards"):
        out.append('<span class="chip">含护栏</span>')
    if card.get("deps"):
        out.append(f'<span class="chip">依赖 {len(card["deps"])}</span>')
    if card.get("has_examples"):
        out.append('<span class="chip">示例</span>')
    if not card.get("has_usage"):
        out.append('<span class="chip chip-warn">未声明用法/IO</span>')
    if card.get("thin"):
        out.append('<span class="chip chip-warn">⚠ 疑薄包装</span>')
    return "".join(out)


def card_html(card: dict) -> str:
    name = card.get("name", "?")
    href = drilldown_href(card)
    slug = skillviz_slug(card)
    loc, nf, stub = card.get("py_loc", 0), card.get("n_funcs", 0), card.get("stub_hits", 0)
    stub_html = f'<b class="warn">{esc(stub)}</b>' if stub else "0"
    stars = card.get("stars")
    star_txt = "" if stars is None else f" · ★{esc(stars)}"
    prov = card.get("provenance", "")
    desc = (card.get("description") or "").strip()
    if len(desc) > 240:
        desc = desc[:238] + "…"

    if href:
        drill = f'<a class="drill" href="{esc(href)}" target="_blank">完整流程图 ↗</a>'
    else:
        cmd = f"/skillviz {slug}"
        # 命令走 data-cmd(经 esc 转义)+ JS 委托复制,不在属性里内联 json,杜绝引号注入
        drill = (f'<button class="drill drill-gen" data-cmd="{esc(cmd)}">'
                 f'生成流程图 · 复制 {esc(cmd)}</button>')

    return f'''
    <div class="card">
      <div class="card-head">
        <span class="card-name">{esc(name)}</span>
        {trust_badge(card.get("trust", "?"), card.get("trust_fail", 0), card.get("trust_warn", 0))}
      </div>
      {fingerprint(card)}
      <div class="chips">{chips(card)}</div>
      <div class="stats">真实代码 <b>{esc(loc)}</b> 行 · <b>{esc(nf)}</b> 函数 · 空壳 {stub_html}{star_txt}</div>
      {f'<div class="desc">{esc(desc)}</div>' if desc else ''}
      <div class="card-foot">
        {drill}
        <span class="prov">{esc(prov)}</span>
      </div>
    </div>'''


def matrix_row(card: dict) -> str:
    s = card.get("shape") or {}
    loc, nf, stub = card.get("py_loc", 0), card.get("n_funcs", 0), card.get("stub_hits", 0)
    stub_html = f'<b class="warn">{esc(stub)}</b>' if stub else "0"
    stars = card.get("stars")
    star_txt = "?" if stars is None else esc(stars)
    lean = KIND_LABEL.get(s.get("lean", "llm"), s.get("lean", ""))
    struct = "流水线" if s.get("structured") else "散文"
    thin = ' <span class="warn">⚠薄</span>' if card.get("thin") else ""
    return (f'<tr>'
            f'<td class="c-name">{esc(card.get("name", "?"))}{thin}</td>'
            f'<td>{trust_badge(card.get("trust", "?"), card.get("trust_fail", 0), card.get("trust_warn", 0))}</td>'
            f'<td class="num">{esc(loc)}·{esc(nf)}·{stub_html}</td>'
            f'<td>{esc(lean)} · {esc(s.get("n_nodes", 0))}节 {esc(struct)}</td>'
            f'<td class="num">{len(card.get("deps", []))}</td>'
            f'<td>{"✓" if card.get("has_examples") else "–"}</td>'
            f'<td class="num">{star_txt}</td>'
            f'</tr>')


CSS = Template("""
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font: 14px/1.6 -apple-system, "PingFang SC", "Helvetica Neue", sans-serif;
         color: $ink; background: $paper; padding: 22px 26px 60px; }
  a { color: $red; text-decoration: none; }
  a:hover { text-decoration: underline; }
  b { font-weight: 700; }
  .warn { color: $red; }

  header h1 { font-size: 20px; }
  header h1 .n { color: $red; }
  header .sub { color: $gray_dark; margin-top: 5px; max-width: 74em; }
  .legend { margin-top: 10px; font-size: 12px; color: $gray_dark;
            display: flex; gap: 16px; flex-wrap: wrap; align-items: center; }
  .legend .dot { display: inline-block; width: 11px; height: 11px; border-radius: 3px;
                 vertical-align: -1px; margin-right: 4px; }
  .legend .d-cli { background: $red; }
  .legend .d-llm { background: $gray_mid; }
  .note { color: $gray_mid; }

  h2.sec { font-size: 12px; color: $gray_dark; text-transform: uppercase; letter-spacing: .5px;
           margin: 26px 0 10px; border-bottom: 1px solid $gray_light; padding-bottom: 5px; }

  table.mx { border-collapse: collapse; width: 100%; max-width: 980px; font-size: 13px; }
  table.mx th { text-align: left; font-size: 11px; color: $gray_mid; font-weight: 600;
                text-transform: uppercase; letter-spacing: .3px; padding: 4px 10px; }
  table.mx td { border-top: 1px solid $gray_light; padding: 7px 10px; vertical-align: middle; }
  table.mx td.c-name { font-weight: 600; }
  table.mx td.num { font-variant-numeric: tabular-nums; color: $gray_dark; }
  table.mx tr:hover td { background: $panel; }

  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
          gap: 14px; margin-top: 6px; }
  .card { border: 1.5px solid $gray_light; border-radius: 10px; padding: 14px 16px;
          background: $paper; display: flex; flex-direction: column; gap: 9px; }
  .card:hover { border-color: $red_mid; }
  .card-head { display: flex; align-items: center; gap: 9px; }
  .card-name { font-weight: 700; font-size: 15px; flex: 1; word-break: break-all; }

  .trust { font-size: 11px; padding: 1px 8px; border-radius: 9px; white-space: nowrap; font-weight: 600; }
  .tr-fail { background: $ink; color: #fff; }
  .tr-warn { background: $paper; color: $gray_dark; border: 1px solid $gray_mid; }
  .tr-pass { background: $gray_light; color: $gray_dark; }

  .fp { display: flex; align-items: center; flex-wrap: wrap; gap: 2px; margin-top: 2px; }
  .seg { display: inline-flex; align-items: center; justify-content: center;
         min-width: 20px; height: 20px; padding: 0 5px; border-radius: 5px;
         font-size: 11px; font-weight: 700; font-variant-numeric: tabular-nums; cursor: default; }
  .seg-cli { background: $red; color: #fff; }
  .seg-llm { background: $gray_light; color: $gray_dark; }
  .seg-none { background: $panel; color: $gray_mid; font-weight: 400; padding: 2px 10px;
              border: 1px dashed $gray_light; }
  .seg-more { background: $paper; color: $gray_mid; border: 1px dashed $gray_mid; font-weight: 400; }
  .seg-sep { color: $gray_mid; font-size: 10px; }
  .fp-label { font-size: 12px; color: $gray_dark; }

  .chips { display: flex; flex-wrap: wrap; gap: 5px; }
  .chip { font-size: 11px; background: $panel; border: 1px solid $gray_light; color: $gray_dark;
          border-radius: 4px; padding: 1px 7px; }
  .chip-mut { color: $gray_mid; }
  .chip-warn { background: $red_pale; border-color: $red_pale; color: $red; }

  .stats { font-size: 12.5px; color: $gray_dark; font-variant-numeric: tabular-nums; }
  .desc { font-size: 12.5px; color: $gray_mid; line-height: 1.55; }

  .card-foot { display: flex; align-items: center; gap: 10px; margin-top: auto;
               padding-top: 8px; border-top: 1px solid $gray_light; }
  .drill { font: 12px -apple-system, "PingFang SC", sans-serif; }
  a.drill { color: $red; font-weight: 600; }
  button.drill { border: 1px solid $gray_light; background: $paper; color: $gray_dark;
                 border-radius: 5px; padding: 3px 9px; cursor: pointer; }
  button.drill:hover { border-color: $red; color: $red; }
  .prov { font-size: 11px; color: $gray_mid; margin-left: auto; word-break: break-all; }

  .toast { position: fixed; bottom: 22px; right: 26px; background: $ink; color: #fff;
           padding: 7px 16px; border-radius: 6px; font-size: 13px; opacity: 0;
           transition: opacity .18s; pointer-events: none; }
  .toast.show { opacity: .93; }
""").safe_substitute(C)


JS = """
function toast(m){var t=document.getElementById('toast');t.textContent=m;t.classList.add('show');
setTimeout(function(){t.classList.remove('show');},1500);}
function copy(text,msg){navigator.clipboard.writeText(text).then(function(){toast(msg||'已复制');});}
document.addEventListener('click',function(e){
  var b=e.target.closest('.drill-gen'); if(!b) return;
  copy(b.getAttribute('data-cmd'),'已复制,切到 Claude Code 粘贴回车生成完整流程图');
});
"""


def build_page(cards: list[dict], title: str, generated: str) -> str:
    # 排序:信任门 FAIL 垫底,其余按星标降序,便于横比时先看可用的
    ordered = sorted(cards, key=lambda c: (c.get("trust") == "FAIL", -(c.get("stars") or 0)))
    matrix = "\n".join(matrix_row(c) for c in ordered)
    grid = "\n".join(card_html(c) for c in ordered)
    n = len(cards)
    return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>skill 结构对比 · {esc(n)} 个候选</title>
<style>{CSS}</style></head>
<body>
<header>
  <h1>skill 结构对比 · <span class="n">{esc(n)}</span> 个候选</h1>
  <div class="sub">{esc(title)}上半是决策级横比矩阵(信任门 / 成色 / 依赖 / 示例),下半每个候选一条<b>形态指纹</b>——读 SKILL.md 得来的分节骨架,让结构差异一眼可见。点候选可下钻到它完整的 skillviz 流程图。</div>
  <div class="legend">
    <span><span class="dot d-cli"></span>命令步(cli)</span>
    <span><span class="dot d-llm"></span>模型步(llm)</span>
    <span>信任门 ✕FAIL / !WARN / ✓PASS</span>
  </div>
  <div class="legend note">指纹读自 SKILL.md → 本地/远程候选<b>对称</b>,是<b>文档结构</b>非验证执行流(真流程点「完整流程图」下钻)。成色列(LOC·脚本)随你抓到多少源码而变,别拿它反证指纹。生成于 {esc(generated)}</div>
</header>

<h2 class="sec">横比矩阵</h2>
<table class="mx">
  <thead><tr><th>候选</th><th>信任门</th><th>成色 LOC·fn·空壳</th><th>结构</th><th>依赖</th><th>示例</th><th>★</th></tr></thead>
  <tbody>
{matrix}
  </tbody>
</table>

<h2 class="sec">形态指纹（点候选下钻完整流程）</h2>
<div class="grid">
{grid}
</div>

<div class="toast" id="toast"></div>
<script>{JS}</script>
</body></html>"""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="skill-selector 结构对比渲染器")
    ap.add_argument("paths", nargs="+",
                    help="compare_candidates 的 --json 文件,或若干 skill/候选目录")
    ap.add_argument("-o", "--output", help="输出 HTML(默认 skillviz/out/skill-compare.html)")
    ap.add_argument("--title", default="", help="页眉附加说明")
    ap.add_argument("--generated", default="", help="生成日期戳(默认今天)")
    ap.add_argument("--open", action="store_true", help="生成后用浏览器打开")
    args = ap.parse_args(argv)

    cards = load_cards(args.paths)
    if not cards:
        sys.exit("没有可渲染的候选")
    for c in cards:            # 缺 shape 的卡(旧 JSON)兜底,不崩
        c.setdefault("shape", {"nodes": [], "n_nodes": 0, "lean": "llm",
                               "structured": False, "has_scripts": False, "has_guards": False})

    generated = args.generated or datetime.date.today().isoformat()
    title = (args.title + " · ") if args.title else ""
    out = args.output or os.path.join(SKILLVIZ_OUT, "skill-compare.html")
    out = os.path.expanduser(out)

    page = build_page(cards, title, generated)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"✓ {out}  （{len(cards)} 个候选）")
    if args.open:
        subprocess.run(["open", out])
    return 0


if __name__ == "__main__":
    sys.exit(main())
