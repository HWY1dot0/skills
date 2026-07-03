# skillviz

[English](README.md) | **简体中文**

把一个 [Claude Code](https://claude.com/claude-code) 的 skill 或斜杠命令，画成一张**可点击的交互式流程图**——每一步在做什么、跑什么命令、输入产物、失败模式，还有每步一键「只调这一步」的调试入口。

它**不是 skill**（没有 `SKILL.md`）——是一个**斜杠命令 + 一个小 Python 渲染器**，所以装法跟本仓里的 skill 不一样。

## 怎么运转（v3）

模型负责理解，渲染器负责画：

- **`/skillviz <名字>`** —— Claude 读这个 skill 的 `.md`（以及它引用的代码），产出一份结构化的 **flow JSON**，用人话描述每一步：做什么、跑什么命令、输入产物、失败模式、子环节。
- **`render_flow.py`** —— 把这份 flow JSON 确定性地渲染成一张单文件 HTML 流程图。不解析 markdown、不猜结构——理解在上游已经完成。
- **`/dbg <名字> [步骤]`** —— 读同一份 flow JSON，在当前会话里只跑某一步；不带步骤号则打印一张编号菜单让你选。流程图上每步都有「复制 `/dbg …`」按钮作为交接。

## 安装

```bash
git clone https://github.com/HWY1dot0/skills.git
cd skills/skillviz

# 1. 装两个斜杠命令
cp commands/skillviz.md commands/dbg.md ~/.claude/commands/
```

命令文件里引用的是作者机器上的路径 `~/Coding/Tools/skillviz/render_flow.py`（及其 `out/` 目录）。你要么把本文件夹克隆到那个位置，要么把 `commands/skillviz.md` 和 `commands/dbg.md` 里那个路径改成本文件夹的实际位置。

需要 Python 3——仅标准库，无依赖。

## 用法

```bash
# 给一个 skill 或命令生成并渲染流程图
/skillviz skill-selector
/skillviz path/to/some-skill.md

# 自己渲染一份已有的 flow JSON
python3 render_flow.py examples/skill-selector.flow.json --open
python3 render_flow.py examples/skill-selector.flow.json --lang en --open

# 在当前会话里只调一步
/dbg skill-selector        # 编号菜单——回一个数字
/dbg skill-selector 3      # 直达第 3 步
```

**界面语言**（栏目标题、按钮、提示）由 `--lang zh|en|auto` 决定——`auto` 跟随 flow 的 `lang` 字段，缺省 `zh`。**内容语言**（每步的 summary/title）则是生成 flow 时用哪种语言写的，就是哪种。

## 示例

用浏览器打开 `examples/skill-selector.html` 看渲染好的流程图——它画的正是本仓自己的 `skill-selector`。产出它的 flow JSON（`examples/skill-selector.flow.json`）就在旁边。

## 协议

MIT。
