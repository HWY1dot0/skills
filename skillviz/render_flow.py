#!/usr/bin/env python3
"""
skillviz v3 渲染器 — flow JSON → 单文件交互式流程图 HTML。

v3 架构反转：LLM（/skillviz command）负责读 skill.md + 关联代码、产出 flow JSON；
本脚本只做确定性渲染，不解析 markdown、不猜结构。

用法:
    python3 render_flow.py out/cpi.flow.json [--open]
    python3 render_flow.py cpi [--open]          # 简写，找 out/cpi.flow.json

flow JSON schema 见 ~/.claude/commands/skillviz.md。
"""
from __future__ import annotations
import sys, os, json, html, argparse, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))

# BOCI mono 红 + 中性灰（~/Coding/charts/palettes.py 同源）
C = {
    "red": "#7E2E33", "red_mid": "#BE6B6F", "red_pale": "#EFD8D9",
    "gray_dark": "#4B5563", "gray_mid": "#9CA3AF", "gray_light": "#E5E7EB",
    "ink": "#1F2328", "paper": "#FFFFFF", "panel": "#F7F7F5",
}

KIND_LABEL = {"cli": "CLI", "llm": "LLM", "mixed": "CLI+LLM"}

# 界面文字(chrome)中英对照。内容(summary/title/…)的语言由生成 flow 的人决定,
# 不在此表;这里只管栏目标题、按钮、提示这些渲染器写死的部分。
LABELS = {
    "zh": {
        "cmds": "条命令", "subs": "个子环节", "fms": "个失败模式", "branch": "步",
        "code": "代码", "out_chip": "产出", "guards": "边界与铁律", "generated": "生成于",
        "empty": "← 点左侧任一步查看详情与调试入口",
        "sec_cmd": "命令", "ph_warn": "红色占位符需先替换成实际值再跑",
        "sec_io": "输入 / 产物", "inputs": "输入", "outputs": "产物",
        "sec_sub": "子环节", "sec_fm": "失败模式",
        "copy": "复制", "copied": "已复制", "cmd_copied": "命令已复制",
        "dbg_hit": "复制 · 直达这一步", "dbg_menu": "复制 · 会话内选单",
        "dbg_hit_toast": "已复制，切到 Claude Code 会话粘贴回车 → 直接单跑这一步",
        "dbg_menu_toast": "已复制，切到 Claude Code 会话粘贴回车 → 出编号菜单，回一个数字即跑",
        "dbg_hint_a": "切到 Claude Code 会话粘贴回车。之后每步迭代都能留在会话敲",
        "dbg_hint_b": "选，不必回图",
    },
    "en": {
        "cmds": "cmds", "subs": "substeps", "fms": "failure modes", "branch": "step",
        "code": "code", "out_chip": "output", "guards": "Boundaries & hard rules", "generated": "generated",
        "empty": "← Pick a step on the left for its details and debug entry",
        "sec_cmd": "Commands", "ph_warn": "Replace the red placeholders with real values before running",
        "sec_io": "Inputs / Outputs", "inputs": "Inputs", "outputs": "Outputs",
        "sec_sub": "Substeps", "sec_fm": "Failure modes",
        "copy": "Copy", "copied": "Copied", "cmd_copied": "Command copied",
        "dbg_hit": "Copy · jump to this step", "dbg_menu": "Copy · in-session menu",
        "dbg_hit_toast": "Copied — paste into a Claude Code session and press enter → runs just this step",
        "dbg_menu_toast": "Copied — paste into a Claude Code session and press enter → a numbered menu appears, reply a number",
        "dbg_hint_a": "Paste into a Claude Code session and press enter. For later iterations stay in the session and type",
        "dbg_hint_b": "to pick — no need to come back to this chart",
    },
}


def esc(s):
    return html.escape(str(s if s is not None else ""), quote=True)


def paras(text):
    """把正文按空行拆成 <p> 段落、段内单换行转 <br>——让长文字有呼吸感，不糊成一坨。"""
    text = str(text or "").replace("\r", "")
    blocks = [b.strip() for b in text.split("\n\n") if b.strip()]
    return "".join(f'<p>{esc(b).replace(chr(10), "<br>")}</p>' for b in blocks)


def load_flow(ref):
    """ref = flow.json 路径，或裸名（找 <HERE>/out/<n>.flow.json）。"""
    if os.path.isfile(ref):
        path = ref
    else:
        path = os.path.join(HERE, "out", f"{ref}.flow.json")
        if not os.path.isfile(path):
            sys.exit(f"找不到 {ref}（也不存在 {path}）。先跑 /skillviz {ref} 生成 flow JSON。")
    with open(path, encoding="utf-8") as f:
        flow = json.load(f)
    # 最小校验：渲染器唯一的"理解"就是这几个字段存在
    if not isinstance(flow.get("steps"), list) or not flow["steps"]:
        sys.exit(f"{path}: steps 缺失或为空")
    for s in flow["steps"]:
        if "id" not in s or "title" not in s:
            sys.exit(f"{path}: 有步骤缺 id/title: {json.dumps(s, ensure_ascii=False)[:80]}")
    return flow, path


# ---------- HTML 片段 ----------

def render_node_card(step, skill, L):
    sid = step["id"]
    kind = step.get("kind", "llm")
    n_cmd = len(step.get("commands", []))
    n_sub = len(step.get("substeps", []))
    meta = []
    if n_cmd:
        meta.append(f'{n_cmd} {L["cmds"]}')
    if n_sub:
        meta.append(f'{n_sub} {L["subs"]}')
    if step.get("failure_modes"):
        meta.append(f'<span class="fm">{len(step["failure_modes"])} {L["fms"]}</span>')
    meta_html = " · ".join(meta)
    # 非默认流向（分支）标签
    branches = ""
    nxt = step.get("next")
    if isinstance(nxt, list):
        labels = []
        for n in nxt:
            if isinstance(n, dict):
                labels.append(f'→ {L["branch"]} {esc(n.get("to"))}（{esc(n.get("when", ""))}）')
        if labels:
            branches = '<div class="branch">' + "<br>".join(labels) + "</div>"
    return f'''
    <div class="node" id="node-{esc(sid)}" data-id="{esc(sid)}" onclick="pick('{esc(sid)}')">
      <div class="node-head">
        <span class="node-num">{esc(sid)}</span>
        <span class="node-title">{esc(step["title"])}</span>
        <span class="badge badge-{esc(kind)}">{esc(KIND_LABEL.get(kind, kind))}</span>
      </div>
      {f'<div class="node-meta">{meta_html}</div>' if meta_html else ''}
      {branches}
    </div>'''


def build_page(flow, name, L):
    skill = flow.get("skill", name)
    title = flow.get("title", skill)
    steps = flow["steps"]
    nodes_html = '\n<div class="arrow">▼</div>\n'.join(
        render_node_card(s, skill, L) for s in steps)

    g = flow.get("globals", {})
    chips = []
    if g.get("code_dir"):
        chips.append(f'<span class="chip">{L["code"]} {esc(g["code_dir"])}</span>')
    for o in g.get("outputs", []):
        chips.append(f'<span class="chip">{L["out_chip"]} {esc(o)}</span>')
    guards = "".join(f"<li>{esc(x)}</li>" for x in g.get("guards", []))
    guards_html = (f'<details class="guards"><summary>{L["guards"]}（{len(g.get("guards", []))}）</summary>'
                   f"<ul>{guards}</ul></details>") if guards else ""

    payload = json.dumps(flow, ensure_ascii=False).replace("</", "<\\/")

    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>skillviz · {esc(skill)}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font: 14px/1.65 -apple-system, "PingFang SC", "Helvetica Neue", sans-serif;
         color: {C['ink']}; background: {C['paper']}; }}
  a {{ color: {C['red']}; }}
  code, .cmd {{ font-family: "SF Mono", Menlo, monospace; font-size: 12.5px; }}

  header {{ padding: 20px 28px 14px; border-bottom: 1px solid {C['gray_light']}; }}
  header h1 {{ font-size: 19px; }}
  header h1 .skill-name {{ color: {C['red']}; }}
  header .overview {{ color: {C['gray_dark']}; margin-top: 6px; max-width: 72em; }}
  header .overview p {{ margin-bottom: 7px; }}
  header .overview p:last-child {{ margin-bottom: 0; }}
  .summary {{ white-space: normal; }}
  .chips {{ margin-top: 8px; }}
  .chip {{ display: inline-block; background: {C['panel']}; border: 1px solid {C['gray_light']};
           border-radius: 4px; padding: 1px 8px; margin: 2px 6px 2px 0; font-size: 12px;
           color: {C['gray_dark']}; }}
  .guards {{ margin-top: 8px; font-size: 13px; color: {C['gray_dark']}; }}
  .guards summary {{ cursor: pointer; user-select: none; }}
  .guards ul {{ margin: 6px 0 0 20px; }}

  .wrap {{ display: flex; height: calc(100vh - 110px); }}
  .flow {{ width: 380px; min-width: 300px; overflow-y: auto; padding: 22px;
           border-right: 1px solid {C['gray_light']}; background: {C['panel']}; }}
  .detail {{ flex: 1; overflow-y: auto; padding: 26px 34px; }}

  .node {{ background: {C['paper']}; border: 1.5px solid {C['gray_light']}; border-radius: 8px;
           padding: 10px 14px; cursor: pointer; transition: border-color .12s; }}
  .node:hover {{ border-color: {C['red_mid']}; }}
  .node.on {{ border-color: {C['red']}; box-shadow: 0 0 0 2px {C['red_pale']}; }}
  .node-head {{ display: flex; align-items: baseline; gap: 8px; }}
  .node-num {{ color: {C['red']}; font-weight: 700; font-size: 15px; }}
  .node-title {{ font-weight: 600; flex: 1; }}
  .badge {{ font-size: 10.5px; padding: 1px 7px; border-radius: 9px; white-space: nowrap; }}
  .badge-cli {{ background: {C['red']}; color: #fff; }}
  .badge-llm {{ background: {C['gray_light']}; color: {C['gray_dark']}; }}
  .badge-mixed {{ background: {C['red_pale']}; color: {C['red']}; }}
  .node-meta {{ font-size: 12px; color: {C['gray_mid']}; margin-top: 3px; }}
  .node-meta .fm {{ color: {C['red_mid']}; }}
  .branch {{ font-size: 12px; color: {C['red']}; margin-top: 4px; }}
  .arrow {{ text-align: center; color: {C['gray_mid']}; font-size: 11px; line-height: 1.9; }}

  .detail h2 {{ font-size: 17px; display: flex; align-items: baseline; gap: 10px; }}
  .detail h2 .node-num {{ font-size: 16px; }}
  .src {{ font-size: 12px; color: {C['gray_mid']}; margin-left: auto; }}
  .summary {{ margin: 12px 0 4px; max-width: 68em; }}
  .sec {{ margin-top: 20px; }}
  .sec > h3 {{ font-size: 13px; color: {C['gray_dark']}; text-transform: uppercase;
               letter-spacing: .4px; border-bottom: 1px solid {C['gray_light']};
               padding-bottom: 4px; margin-bottom: 8px; }}

  .cmdrow {{ display: flex; align-items: center; gap: 8px; background: {C['panel']};
             border: 1px solid {C['gray_light']}; border-radius: 6px;
             padding: 7px 10px; margin-bottom: 6px; }}
  .cmdrow .cmd {{ flex: 1; word-break: break-all; }}
  .cmd .ph {{ color: {C['red']}; font-weight: 600; }}
  button {{ font: 12px -apple-system, "PingFang SC", sans-serif; border: 1px solid {C['gray_light']};
            background: {C['paper']}; color: {C['gray_dark']}; border-radius: 5px;
            padding: 3px 10px; cursor: pointer; white-space: nowrap; }}
  button:hover {{ border-color: {C['red']}; color: {C['red']}; }}
  button.hot {{ background: {C['red']}; border-color: {C['red']}; color: #fff; }}
  button.hot:hover {{ background: #6a262b; }}

  .io {{ display: flex; gap: 26px; flex-wrap: wrap; }}
  .io div {{ min-width: 220px; }}
  .io h4 {{ font-size: 12px; color: {C['gray_mid']}; margin-bottom: 4px; }}
  .io ul, .fmtab td ul {{ margin-left: 18px; }}

  .sub {{ border: 1px solid {C['gray_light']}; border-radius: 6px; margin-bottom: 8px; }}
  .sub summary {{ cursor: pointer; padding: 8px 12px; font-weight: 600; user-select: none; }}
  .sub summary:hover {{ color: {C['red']}; }}
  .sub .sub-body {{ padding: 2px 14px 12px; color: {C['ink']}; }}
  .sub .sub-body p {{ color: {C['gray_dark']}; margin-bottom: 6px; }}
  .sub .sub-body ul {{ margin-left: 18px; }}
  .sub .sub-body li {{ margin: 2px 0; }}

  table.fmtab {{ border-collapse: collapse; width: 100%; max-width: 60em; }}
  table.fmtab td {{ border: 1px solid {C['gray_light']}; padding: 6px 10px; vertical-align: top; }}
  table.fmtab td:first-child {{ color: {C['red']}; width: 32%; }}

  .dbgbar {{ margin-top: 26px; padding: 12px 14px; background: {C['red_pale']};
             border-radius: 8px; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }}
  .dbgbar .cmd {{ color: {C['red']}; font-weight: 600; }}
  .dbgbar .hint {{ flex-basis: 100%; }}
  .dbgbar .hint code {{ background: rgba(126,46,51,0.10); padding: 0 4px; border-radius: 3px; }}
  .dbgbar .hint {{ font-size: 12px; color: {C['gray_dark']}; }}
  .empty {{ color: {C['gray_mid']}; padding-top: 40vh; text-align: center; }}
  .toast {{ position: fixed; bottom: 22px; right: 26px; background: {C['ink']}; color: #fff;
            padding: 7px 16px; border-radius: 6px; font-size: 13px; opacity: 0;
            transition: opacity .18s; pointer-events: none; }}
  .toast.show {{ opacity: .92; }}
</style>
</head>
<body>
<header>
  <h1><span class="skill-name">/{esc(skill)}</span> · {esc(title)}
      <span class="src">{esc(flow.get("source", ""))} · {L["generated"]} {esc(flow.get("generated", ""))}</span></h1>
  <div class="overview">{paras(flow.get("overview", ""))}</div>
  <div class="chips">{''.join(chips)}</div>
  {guards_html}
</header>
<div class="wrap">
  <div class="flow">{nodes_html}</div>
  <div class="detail" id="detail"><div class="empty">{esc(L["empty"])}</div></div>
</div>
<div class="toast" id="toast"></div>

<script type="application/json" id="flow-data">{payload}</script>
<script>
const FLOW = JSON.parse(document.getElementById('flow-data').textContent);
const SKILL = FLOW.skill || {json.dumps(skill, ensure_ascii=False)};
const L = {json.dumps(L, ensure_ascii=False)};
const byId = Object.fromEntries(FLOW.steps.map(s => [String(s.id), s]));

function escHtml(s) {{
  return String(s ?? '').replace(/[&<>"]/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}})[c]);
}}
function nl2br(s) {{ return escHtml(s).replace(/\\n/g, '<br>'); }}
function fmtCmd(c) {{  // <占位符> 标红
  return escHtml(c).replace(/&lt;([^&]{{1,40}}?)&gt;/g, '<span class="ph">&lt;$1&gt;</span>');
}}
function toast(msg) {{
  const t = document.getElementById('toast');
  t.textContent = msg; t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 1400);
}}
function copy(text, msg) {{
  navigator.clipboard.writeText(text).then(() => toast(msg || L.copied));
}}

function pick(id) {{
  document.querySelectorAll('.node').forEach(n => n.classList.toggle('on', n.dataset.id === String(id)));
  const s = byId[String(id)];
  if (!s) return;
  let h = `<h2><span class="node-num">${{escHtml(s.id)}}</span> ${{escHtml(s.title)}}` +
          (s.source_lines ? `<span class="src">${{escHtml(FLOW.source_basename || '')}}:${{escHtml(s.source_lines)}}</span>` : '') + `</h2>`;
  if (s.summary) h += `<p class="summary">${{nl2br(s.summary)}}</p>`;

  if ((s.commands || []).length) {{
    h += `<div class="sec"><h3>${{L.sec_cmd}}</h3>` + s.commands.map(c =>
      `<div class="cmdrow"><span class="cmd">${{fmtCmd(c)}}</span>` +
      `<button onclick='copy(${{JSON.stringify(c)}}, ${{JSON.stringify(L.cmd_copied)}})'>${{L.copy}}</button></div>`).join('') + `</div>`;
    if (s.commands.some(c => /<[^>]+>/.test(c)))
      h += `<div class="hint" style="font-size:12px;color:{C['red']}">${{L.ph_warn}}</div>`;
  }}

  if ((s.inputs || []).length || (s.outputs || []).length) {{
    h += `<div class="sec"><h3>${{L.sec_io}}</h3><div class="io">`;
    if ((s.inputs || []).length)
      h += `<div><h4>${{L.inputs}}</h4><ul>` + s.inputs.map(x => `<li>${{escHtml(x)}}</li>`).join('') + `</ul></div>`;
    if ((s.outputs || []).length)
      h += `<div><h4>${{L.outputs}}</h4><ul>` + s.outputs.map(x => `<li>${{escHtml(x)}}</li>`).join('') + `</ul></div>`;
    h += `</div></div>`;
  }}

  if ((s.substeps || []).length) {{
    h += `<div class="sec"><h3>${{L.sec_sub}}（${{s.substeps.length}}）</h3>` + s.substeps.map(u => {{
      let b = '';
      if (u.summary) b += `<p>${{escHtml(u.summary)}}</p>`;
      if ((u.items || []).length)
        b += `<ul>` + u.items.map(i => `<li>${{escHtml(i)}}</li>`).join('') + `</ul>`;
      return `<details class="sub"><summary>${{escHtml(u.title)}}</summary><div class="sub-body">${{b}}</div></details>`;
    }}).join('') + `</div>`;
  }}

  if ((s.failure_modes || []).length) {{
    h += `<div class="sec"><h3>${{L.sec_fm}}</h3><table class="fmtab">` + s.failure_modes.map(f =>
      `<tr><td>${{escHtml(f.case)}}</td><td>${{escHtml(f.action)}}</td></tr>`).join('') + `</table></div>`;
  }}

  const dbg = `/dbg ${{SKILL}} ${{s.id}}`;
  const dbgMenu = `/dbg ${{SKILL}}`;
  h += `<div class="dbgbar"><span class="cmd">${{escHtml(dbg)}}</span>` +
       `<button class="hot" onclick='copy(${{JSON.stringify(dbg)}}, ${{JSON.stringify(L.dbg_hit_toast)}})'>${{L.dbg_hit}}</button>` +
       `<button onclick='copy(${{JSON.stringify(dbgMenu)}}, ${{JSON.stringify(L.dbg_menu_toast)}})'>${{L.dbg_menu}}</button>` +
       `<span class="hint">${{L.dbg_hint_a}} <code>${{escHtml(dbgMenu)}}</code> ${{L.dbg_hint_b}}</span></div>`;

  document.getElementById('detail').innerHTML = h;
  document.getElementById('detail').scrollTop = 0;
}}
</script>
</body>
</html>"""


def main():
    ap = argparse.ArgumentParser(description="skillviz v3: flow JSON → 流程图 HTML")
    ap.add_argument("flow", help="flow.json 路径，或裸名（找 out/<n>.flow.json）")
    ap.add_argument("-o", "--output", help="输出 HTML 路径（默认 flow.json 同目录同名 .html）")
    ap.add_argument("--lang", choices=["auto", "zh", "en"], default="auto",
                    help="界面文字语言（auto=跟随 flow 的 lang 字段，缺省 zh）；内容语言由 flow 本身决定")
    ap.add_argument("--open", action="store_true", help="生成后用默认浏览器打开")
    args = ap.parse_args()

    flow, src_path = load_flow(args.flow)
    flow["source_basename"] = os.path.basename(flow.get("source", ""))
    name = flow.get("skill") or os.path.basename(src_path).replace(".flow.json", "")
    out = args.output or src_path.replace(".flow.json", ".html")
    if out == src_path:
        out = os.path.splitext(src_path)[0] + ".html"

    lang = args.lang if args.lang != "auto" else (
        flow.get("lang") if flow.get("lang") in LABELS else "zh")
    html_text = build_page(flow, name, LABELS[lang])
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html_text)
    print(f"✓ {out}  （{len(flow['steps'])} 步）")
    if args.open:
        subprocess.run(["open", out])


if __name__ == "__main__":
    main()
