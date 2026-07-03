# skillviz

[English](README.md) | **简体中文**

一个 [Claude Code](https://claude.com/claude-code) **技能（skill）**，把一个 skill 或斜杠命令画成一张**可点击的交互式流程图**——每一步在做什么、跑什么命令、输入产物、失败模式，还有每步一键交给调试器只跑那一步。

它**自动触发**：你说「画出 cpi 的流程」「skillviz 一下 skill-selector」「visualize how skill-selector works」它就出动，不用点名。它自带渲染器 `render_flow.py`，并附一个配套的 `/dbg` 命令用来逐步调试。

## 怎么运转（v3）

模型负责理解，渲染器负责画：

- **技能本身** —— 读目标 skill 的 `.md`（以及它引用的代码），产出一份结构化的 **flow JSON**，用人话描述每一步：做什么、跑什么命令、输入产物、失败模式、子环节。
- **`render_flow.py`** —— 把这份 flow JSON 确定性地渲染成一张单文件 HTML 流程图。不解析 markdown、不猜结构——理解在上游已经完成。渲染器就打包在技能里，没有路径要配。
- **`/dbg <名字> [步骤]`**（配套命令）—— 读同一份 flow JSON，在当前会话里只跑某一步；不带步骤号则打印一张编号菜单让你选。流程图上每步都有「复制 `/dbg …`」按钮作为交接。

## 安装

```bash
git clone https://github.com/HWY1dot0/skills.git
cd skills

# 技能（软链进你的 Claude Code skills 目录）
ln -s "$(pwd)/skillviz" ~/.claude/skills/skillviz

# 配套的 /dbg 命令
cp skillviz/commands/dbg.md ~/.claude/commands/
```

需要 Python 3——仅标准库，无依赖。渲染器就在技能里，别的什么都不用接。

## 用法

```bash
# 直接说——技能自动触发，没有斜杠命令要记：
#   「画出 cpi 的流程」   「skillviz 一下 skill-selector」   「visualize how skill-selector works」

# 自己渲染一份已有的 flow JSON（在本文件夹里）
python3 render_flow.py examples/skill-selector.flow.json --open
python3 render_flow.py examples/skill-selector.flow.json --lang en --open

# 在当前会话里只调一步（配套命令）
/dbg skill-selector        # 编号菜单——回一个数字
/dbg skill-selector 3      # 直达第 3 步
```

**界面语言**（栏目标题、按钮、提示）由 `--lang zh|en|auto` 决定——`auto` 跟随 flow 的 `lang` 字段，缺省 `zh`。**内容语言**（每步的 summary/title）则是生成 flow 时用哪种语言写的，就是哪种。

## 示例

用浏览器打开 `examples/skill-selector.html` 看渲染好的流程图——它画的正是本仓自己的 `skill-selector`。产出它的 flow JSON（`examples/skill-selector.flow.json`）就在旁边。

## 协议

MIT。
