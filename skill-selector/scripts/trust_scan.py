#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
trust_scan.py — 自动化 skill-selector 的信任门(Step 3 GATE)+ 空壳检测。

把"读它的源码再决定要不要采用"从人工变成一道能跑的闸。只抓**确定性**信号
(危险调用、注入式指令、空壳实现);感知性判断(它真值不值得信)仍归人。
设计前提:**坏 skill 比没 skill 更糟** —— 宁可多报,让你逐条看。

三类信号
--------
A. 危险动作(代码)—— 网络 / shell-out / eval·exec / 读凭证·敏感路径 / 混淆;
   且"网络 + 读密钥/文件"的组合升级为疑似外泄(FAIL)。
B. 注入式指令(SKILL.md 等文本)—— 写给"模型"而非"任务"的指令:忽略上文、
   别告诉用户、把 X 发到某地址、读取密钥等。
C. 空壳 / 假实现 —— "有脚本"≠"脚本干事":函数直接 return 常量、空函数体、
   `# Real implementation would…` / TODO / NotImplementedError 之类占位。

用法
----
    python trust_scan.py <skill_dir_or_file> [--json] [--quiet]
    python trust_scan.py /tmp/candidates/Some__skill

退出码:0=PASS  1=有 WARN  2=有 FAIL

注:这是确定性**首道闸**,不是信任门全部 —— 它判不了意图、抓不住措辞高明的注入,
所以 references/trust-and-safety-review.md 的感知性检查仍要走。另:别拿它扫自己的
规则文件 —— 模式型扫描器会命中它存着的那些"坏字符串"(预期现象,非 bug)。
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path

SEV_FAIL, SEV_WARN, SEV_INFO = "FAIL", "WARN", "INFO"


@dataclass
class Finding:
    severity: str
    code: str
    message: str
    file: str = ""
    line: int = 0


# ── 词表/模式(模块级,可在 import 后扩展)─────────────────────────────────

# 网络相关模块(import 即提示——制图/写作类 skill 本不该联网)
NET_MODULES = {
    "socket", "requests", "httpx", "aiohttp", "urllib", "urllib.request",
    "http.client", "httplib", "ftplib", "smtplib", "telnetlib", "paramiko",
    "websocket", "websockets", "pycurl",
}
# 执行/反序列化相关
EXEC_MODULES = {"subprocess", "pty", "commands"}
DESERIAL = {"pickle", "marshal", "shelve", "dill"}

# os.environ 中疑似密钥的键名
SECRET_KEY_RE = re.compile(r"(TOKEN|SECRET|PASSWORD|PASSWD|API[_-]?KEY|ACCESS[_-]?KEY|"
                           r"PRIVATE[_-]?KEY|CREDENTIAL)", re.I)
# 敏感路径字面量
SENSITIVE_PATH_RE = re.compile(
    r"\.ssh|\.aws|\.config/gh|\.netrc|/etc/passwd|/etc/shadow|"
    r"\.env\b|id_rsa|credentials|keychain|\.docker/config", re.I)

# 占位/空壳标记(注释或字符串)
STUB_MARKERS = [
    r"real\s+implementation\s+would", r"actual\s+implementation",
    r"\bplaceholder\b", r"\bstub\b", r"not\s+implemented", r"to\s*do\b", r"\bfixme\b",
    r"for\s+now\b", r"simplified\s+version", r"in\s+a\s+real\b", r"假实现", r"占位",
]
STUB_MARKER_RE = re.compile("|".join(STUB_MARKERS), re.I)

# 函数名暗示"该有真计算"的(空壳更可疑)
COMPUTE_NAME_RE = re.compile(
    r"score|evaluat|assess|check|calc|comput|analy|rank|rate|verify|audit|detect|measure", re.I)

# 注入式指令(写给模型的)——在 .md/.txt 文本里
INJECTION_PATTERNS = [
    (r"ignore\s+(?:all\s+)?(?:previous|above|prior)\s+instructions", SEV_FAIL),
    (r"disregard\s+(?:the\s+)?(?:system|previous|above)", SEV_FAIL),
    (r"do\s+not\s+(?:tell|inform|mention\s+to)\s+the\s+user", SEV_FAIL),
    (r"(?:without|don'?t)\s+(?:telling|informing|asking)\s+the\s+user", SEV_FAIL),
    (r"(?:send|post|exfiltrate|upload|leak)\s+(?:it|them|the|this|your|all)?\s*"
     r"(?:to\s+)?https?://", SEV_FAIL),
    (r"reveal\s+(?:your|the)\s+(?:system\s+prompt|instructions|api[_\s-]?key)", SEV_FAIL),
    (r"忽略(?:以上|之前|前面)(?:所有)?指令", SEV_FAIL),
    (r"不要(?:告诉|告知)用户", SEV_FAIL),
    (r"you\s+must\s+(?:always|never)\b", SEV_WARN),
    (r"as\s+an?\s+ai\b.*?(?:you\s+should|must)", SEV_WARN),
]

# 不可见/方向控制字符 —— 隐写与视觉欺骗的载体,正经 skill 文本里几乎不该出现。
# (references/trust-and-safety-review.md 把它列为 FAIL 级红旗,这里落实成机器检查。)
# 一律用 \u 转义写:源码自身不能含真实零宽字符(不然又是一处自指误报+编辑器隐患)。
BIDI_RE = re.compile("[\u202a-\u202e\u2066-\u2069]")        # RLO 类双向控制 → FAIL
INVIS_RE = re.compile("[\u200b\u200c\u200e\u200f\u2060-\u2064\u00ad\ufeff]")  # 零宽类 → WARN
ZWJ = "\u200d"                                              # emoji 连接子里合法,单独判

# 超长 base64 字面量(可藏 payload;data:image 内联图降为 INFO)
B64_BLOB_RE = re.compile(r"[A-Za-z0-9+/]{120,}={0,2}")

# shell / js 文本里的危险串
SHELL_DANGER = [
    (r"\bcurl\b[^\n|]*\|\s*(?:bash|sh)\b", SEV_FAIL, "curl | bash 远程执行"),
    (r"\bwget\b[^\n|]*\|\s*(?:bash|sh)\b", SEV_FAIL, "wget | sh 远程执行"),
    (r"\beval\s*\(", SEV_FAIL, "eval 动态执行"),
    (r"child_process|execSync|spawnSync", SEV_WARN, "Node 子进程执行"),
    (r"\bbase64\s+(?:-d|--decode)\b", SEV_WARN, "base64 解码(常配合混淆)"),
    (r"https?://", SEV_INFO, "外部 URL"),
]


# ── 通用字符层检查(代码与文本共用)────────────────────────────────────

def _scan_common(src: str, rel: str) -> list[Finding]:
    """不可见字符 + 长 base64 blob。任何已读入的源文本都过一遍。"""
    out: list[Finding] = []
    for m in BIDI_RE.finditer(src):
        out.append(Finding(SEV_FAIL, "BIDI_CHAR",
                           f"双向控制字符 U+{ord(m.group(0)):04X}(可视觉伪装代码/文件名)",
                           rel, src.count("\n", 0, m.start()) + 1))
    for m in INVIS_RE.finditer(src):
        if m.group(0) == "\ufeff" and m.start() == 0:       # 文件头 BOM 合法
            continue
        out.append(Finding(SEV_WARN, "INVISIBLE_CHAR",
                           f"不可见字符 U+{ord(m.group(0)):04X}(可藏指令/混淆)",
                           rel, src.count("\n", 0, m.start()) + 1))
    for m in re.finditer(ZWJ, src):
        i = m.start()
        prev_c = src[i - 1] if i else ""
        next_c = src[i + 1] if i + 1 < len(src) else ""
        if (prev_c and ord(prev_c) > 127) or (next_c and ord(next_c) > 127):
            continue                                             # emoji ZWJ 序列,放过
        out.append(Finding(SEV_WARN, "INVISIBLE_CHAR",
                           "零宽连接符 U+200D 出现在纯 ASCII 上下文(非 emoji)",
                           rel, src.count("\n", 0, i) + 1))
    for m in B64_BLOB_RE.finditer(src):
        ctx = src[max(0, m.start() - 40):m.start()]
        inline_img = "data:image" in ctx
        out.append(Finding(SEV_INFO if inline_img else SEV_WARN, "B64_BLOB",
                           f"长 base64 字面量({len(m.group(0))} 字符"
                           + (",内联图片)" if inline_img else ") —— 可藏 payload,解码确认去向"),
                           rel, src.count("\n", 0, m.start()) + 1))
    return out


# ── Python AST 分析 ────────────────────────────────────────────────────

def _scan_python(path: Path, rel: str) -> list[Finding]:
    out: list[Finding] = []
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return out
    out += _scan_common(src, rel)
    # 占位标记(注释/字符串,正则即可)
    for m in STUB_MARKER_RE.finditer(src):
        out.append(Finding(SEV_WARN, "STUB_MARKER", f"占位/假实现标记:'{m.group(0)}'",
                           rel, src.count("\n", 0, m.start()) + 1))
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        out.append(Finding(SEV_INFO, "PARSE", f"无法解析 Python:{e}", rel, e.lineno or 0))
        return out

    net = exec_ = False

    for node in ast.walk(tree):
        # import 网络/执行/反序列化模块
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            else:
                mods = [node.module or ""]
            for mod in mods:
                base = (mod or "").split(".")[0]
                full = mod or ""
                if base in {m.split(".")[0] for m in NET_MODULES} or full in NET_MODULES:
                    net = True
                    out.append(Finding(SEV_WARN, "NET_IMPORT",
                                       f"导入网络模块 '{mod}' —— 这个 skill 需要联网吗?确认是否预期",
                                       rel, node.lineno))
                if base in EXEC_MODULES:
                    exec_ = True
                    out.append(Finding(SEV_WARN, "EXEC_IMPORT",
                                       f"导入执行模块 '{mod}'(subprocess 等)", rel, node.lineno))
                if base in DESERIAL:
                    out.append(Finding(SEV_WARN, "DESERIAL_IMPORT",
                                       f"导入反序列化模块 '{mod}'(pickle/marshal 可执行任意代码)",
                                       rel, node.lineno))
        # 危险调用 —— 按带点全名精确判,避免误伤 re.compile / json.loads
        if isinstance(node, ast.Call):
            qual = _qual(node.func)
            last, first = qual.split(".")[-1], qual.split(".")[0]
            if qual in {"eval", "exec"}:                         # 内置 eval/exec
                out.append(Finding(SEV_FAIL, "DANGER_CALL", f"危险调用 {qual}() —— 动态执行任意代码",
                                   rel, node.lineno)); exec_ = True
            elif qual == "__import__":
                out.append(Finding(SEV_WARN, "DANGER_CALL", "__import__()(动态导入)", rel, node.lineno))
            elif qual == "compile":                              # 仅内置 compile,放过 re.compile
                out.append(Finding(SEV_WARN, "DANGER_CALL", "内置 compile()(常与 exec 配对)", rel, node.lineno))
            elif qual in {"os.system", "os.popen"}:
                out.append(Finding(SEV_FAIL, "DANGER_CALL", f"{qual}() 执行 shell", rel, node.lineno)); exec_ = True
            elif qual.startswith("os.spawn") or qual == "os.posix_spawn":
                out.append(Finding(SEV_WARN, "DANGER_CALL", f"{qual}()(进程派生)", rel, node.lineno))
            elif last == "loads" and first in {"pickle", "marshal", "dill", "shelve", "cloudpickle"}:
                out.append(Finding(SEV_WARN, "DESERIAL", f"{qual}()(反序列化可执行任意代码)", rel, node.lineno))
            elif last in {"b64decode", "b85decode", "b32decode", "a85decode"}:
                out.append(Finding(SEV_WARN, "B64_DECODE",
                                   f"{qual}()(解码常配合混淆 —— 查解码结果的去向)", rel, node.lineno))
            elif first == "subprocess" and last in {"run", "call", "Popen", "check_output", "check_call", "getoutput"}:
                exec_ = True
                shell_true = any(isinstance(k.value, ast.Constant) and k.value.value is True
                                 for k in node.keywords if k.arg == "shell")
                sev = SEV_FAIL if shell_true else SEV_WARN
                out.append(Finding(sev, "SUBPROCESS",
                                   f"subprocess.{last}()" + ("(shell=True,可注入)" if shell_true else ""),
                                   rel, node.lineno))
        # os.environ 读密钥
        if isinstance(node, ast.Subscript) and "environ" in ast.dump(node.value):
            key = node.slice
            if isinstance(key, ast.Constant) and isinstance(key.value, str) and SECRET_KEY_RE.search(key.value):
                out.append(Finding(SEV_FAIL, "SECRET_ENV",
                                   f"读取疑似密钥环境变量 '{key.value}'", rel, node.lineno))
        # 字符串字面量里的敏感路径
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and SENSITIVE_PATH_RE.search(node.value):
            out.append(Finding(SEV_FAIL, "SENSITIVE_PATH",
                               f"引用敏感路径 '{node.value[:40]}'", rel, getattr(node, "lineno", 0)))
        # 函数级:空壳 / 常量返回
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out += _check_func_stub(node, rel)
        # raise NotImplementedError
        if isinstance(node, ast.Raise) and node.exc is not None and \
           "NotImplementedError" in ast.dump(node.exc):
            out.append(Finding(SEV_WARN, "NOT_IMPLEMENTED", "raise NotImplementedError(未实现)",
                               rel, node.lineno))

    # 组合:网络 + 读密钥/敏感路径 → 疑似外泄(高置信)。
    # 注意:不拿"网络 + 普通 open()"当信号——下载类工具都写文件,会大量误报。
    has_secret = any(f.code in {"SECRET_ENV", "SENSITIVE_PATH"} for f in out)
    if net and has_secret:
        out.append(Finding(SEV_FAIL, "EXFIL_COMBO",
                           "网络 + 读取密钥/敏感路径 同时出现 —— 疑似数据外泄,务必逐行确认", rel, 0))
    return out


def _qual(func) -> str:
    """带点的全名:os.system / re.compile / pickle.loads / 裸 eval。"""
    parts: list[str] = []
    n = func
    while isinstance(n, ast.Attribute):
        parts.append(n.attr)
        n = n.value
    if isinstance(n, ast.Name):
        parts.append(n.id)
    return ".".join(reversed(parts))


def _check_func_stub(fn, rel: str) -> list[Finding]:
    body = [n for n in fn.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
                                       and isinstance(n.value.value, str))]  # 去掉 docstring
    # 空壳:只剩 pass / ...
    if not body or all(isinstance(n, ast.Pass) or
                       (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
                        and n.value.value is ...) for n in body):
        return [Finding(SEV_WARN, "EMPTY_FUNC", f"空函数体 '{fn.name}'(只有 pass/...)", rel, fn.lineno)]
    # 常量返回 + 无真计算:典型"假评分/假检查"
    returns = [n for n in ast.walk(fn) if isinstance(n, ast.Return) and n.value is not None]
    if returns:
        has_logic = any(isinstance(n, (ast.If, ast.For, ast.While, ast.Call, ast.BinOp,
                                       ast.Compare, ast.BoolOp, ast.ListComp, ast.DictComp))
                        for n in ast.walk(fn))
        all_const = all(_is_constish(r.value) for r in returns)
        if all_const and not has_logic and COMPUTE_NAME_RE.search(fn.name):
            return [Finding(SEV_WARN, "HARDCODED_RETURN",
                            f"'{fn.name}' 直接返回硬编码常量、无任何计算 —— 疑似空壳(看着像在评估,其实没做事)",
                            rel, fn.lineno)]
    return []


def _is_constish(node) -> bool:
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, (ast.Dict, ast.List, ast.Tuple, ast.Set)):
        kids = list(ast.iter_child_nodes(node))
        return all(_is_constish(k) for k in kids) if kids else True
    return False


# ── 文本(.md/.sh/.js/.txt)分析 ─────────────────────────────────────────

def _scan_text(path: Path, rel: str) -> list[Finding]:
    out: list[Finding] = []
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return out
    out += _scan_common(src, rel)
    suffix = path.suffix.lower()
    # 注入式指令(主要针对 .md / SKILL 文本)
    if suffix in {".md", ".txt", ".rst", ""}:
        for pat, sev in INJECTION_PATTERNS:
            for m in re.finditer(pat, src, re.I):
                out.append(Finding(sev, "INJECTION",
                                   f"疑似写给模型的注入式指令:'{m.group(0)[:50]}'",
                                   rel, src.count("\n", 0, m.start()) + 1))
    # shell/js 危险串
    if suffix in {".sh", ".bash", ".zsh", ".js", ".mjs", ".ts"} or "#!/" in src[:40]:
        for pat, sev, why in SHELL_DANGER:
            for m in re.finditer(pat, src, re.I):
                out.append(Finding(sev, "SHELL_DANGER", f"{why}:'{m.group(0)[:40]}'",
                                   rel, src.count("\n", 0, m.start()) + 1))
    # 占位标记(任何文本)
    for m in STUB_MARKER_RE.finditer(src):
        out.append(Finding(SEV_INFO, "STUB_MARKER", f"占位/未完成标记:'{m.group(0)}'",
                           rel, src.count("\n", 0, m.start()) + 1))
    return out


# ── 主入口 ─────────────────────────────────────────────────────────────

CODE_EXT = {".py"}
TEXT_EXT = {".md", ".txt", ".rst", ".sh", ".bash", ".zsh", ".js", ".mjs", ".ts", ""}
SKIP_DIRS = {"__pycache__", "node_modules", ".git", "assets", "examples"}
# 不在扫描范围但**可执行/可藏指令**的类型 —— 出现即 WARN(其余未覆盖类型仅 INFO)
RISKY_UNSCANNED = {".ipynb", ".yaml", ".yml", ".rb", ".pl", ".php", ".ps1", ".bat",
                   ".cmd", ".exe", ".dll", ".so", ".dylib", ".bin", ".wasm", ".jar", ".pyc"}


def walk_files(root: Path, skip_dirs: set[str] = SKIP_DIRS):
    """os.walk(followlinks=True) —— rglob 不跟目录级 symlink,symlink 装的内容会静默消失。"""
    seen: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
        rp = os.path.realpath(dirpath)
        if rp in seen:                          # symlink 环路保护
            dirnames[:] = []
            continue
        seen.add(rp)
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for fn in sorted(filenames):
            yield Path(dirpath) / fn


def scan(target: Path) -> list[Finding]:
    files = [target] if target.is_file() else list(walk_files(target))
    findings: list[Finding] = []
    unscanned: list[tuple[str, str]] = []
    root = target if target.is_dir() else target.parent
    for p in files:
        rel = str(p.relative_to(root)) if target.is_dir() else p.name
        suf = p.suffix.lower()
        if suf in CODE_EXT:
            findings += _scan_python(p, rel)
        elif suf in TEXT_EXT:
            findings += _scan_text(p, rel)
        else:
            unscanned.append((rel, suf))
    # fail-closed 的可见性:没扫的文件不能装作不存在 —— PASS 只对已扫范围负责。
    risky = [r for r, s in unscanned if s in RISKY_UNSCANNED]
    if risky:
        findings.append(Finding(SEV_WARN, "UNSCANNED",
                                f"{len(risky)} 个可执行/可藏指令类型的文件不在扫描范围,须人工看:"
                                + ", ".join(risky[:6]) + ("…" if len(risky) > 6 else "")))
    benign = [r for r, s in unscanned if s not in RISKY_UNSCANNED]
    if benign:
        findings.append(Finding(SEV_INFO, "UNSCANNED",
                                f"{len(benign)} 个文件类型不在扫描范围(多为资产/数据),本报告对其无意见:"
                                + ", ".join(benign[:6]) + ("…" if len(benign) > 6 else "")))
    order = {SEV_FAIL: 0, SEV_WARN: 1, SEV_INFO: 2}
    findings.sort(key=lambda f: (order.get(f.severity, 9), f.file, f.line))
    return findings


def summarize(findings: list[Finding]) -> dict:
    n_fail = sum(1 for f in findings if f.severity == SEV_FAIL)
    n_warn = sum(1 for f in findings if f.severity == SEV_WARN)
    n_info = sum(1 for f in findings if f.severity == SEV_INFO)
    verdict = "FAIL" if n_fail else ("WARN" if n_warn else "PASS")
    return {"verdict": verdict, "fail": n_fail, "warn": n_warn, "info": n_info, "total": len(findings)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="skill-selector 信任门 + 空壳扫描")
    ap.add_argument("path", help="skill 目录或单个文件")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--quiet", action="store_true", help="只输出结论行")
    ap.add_argument("--baseline", default=None,
                    help="上次 --json 输出的文件;只报相对它**新增**的 findings"
                         "(复审升级版候选时,已人工确认过 benign 的不再刷屏)")
    args = ap.parse_args(argv)

    target = Path(args.path).expanduser()
    if not target.exists():
        print(f"error: 不存在 {target}", file=sys.stderr)
        return 2

    findings = scan(target)
    suppressed = 0
    if args.baseline:
        try:
            base = json.loads(Path(args.baseline).expanduser().read_text(encoding="utf-8"))
            known = {(f["code"], f["file"], f["message"]) for f in base.get("findings", [])}
            kept = [f for f in findings if (f.code, f.file, f.message) not in known]
            suppressed = len(findings) - len(kept)
            findings = kept
        except Exception as e:  # noqa: BLE001
            print(f"warn: baseline 读取失败,按全量报告:{e}", file=sys.stderr)
    s = summarize(findings)

    if args.json:
        print(json.dumps({"summary": s, "findings": [asdict(f) for f in findings]},
                         ensure_ascii=False, indent=2))
        return 2 if s["verdict"] == "FAIL" else (1 if s["verdict"] == "WARN" else 0)

    icon = {SEV_FAIL: "[FAIL]", SEV_WARN: "[WARN]", SEV_INFO: "[info]"}
    if not args.quiet:
        print(f"==== trust_scan  {target.name} ====")
        for f in findings:
            loc = f"{f.file}:{f.line}" if f.line else f.file
            print(f"{icon[f.severity]}  {loc}  {f.code}: {f.message}")
    badge = {"PASS": "PASS ✅", "WARN": "WARN ⚠️", "FAIL": "FAIL ❌"}[s["verdict"]]
    extra = f"  [baseline 已隐去 {suppressed} 条旧 finding]" if suppressed else ""
    print(f"---- {badge}  (FAIL {s['fail']} / WARN {s['warn']} / INFO {s['info']}) ----{extra}")
    if s["verdict"] == "FAIL":
        print("→ 有 FAIL:逐条确认前不要采用。危险动作/注入/外泄须人工核实是否恶意。")
    return 2 if s["verdict"] == "FAIL" else (1 if s["verdict"] == "WARN" else 0)


if __name__ == "__main__":
    sys.exit(main())
