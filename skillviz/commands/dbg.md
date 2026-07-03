---
description: "定点调试一个 skill 的某一步：从 skillviz flow JSON 取该步的范围与命令，只执行那一步、做完即停。用法 /dbg <skill>（不带步骤号 → 会话内出编号菜单，回一个数字即跑）或 /dbg <skill> <步骤号|标题片段>（直达），如 /dbg cpi、/dbg cpi 3、/dbg cpi 异常值。当用户提到 dbg、调试某一步、单跑某步、定点调试 时触发。"
argument-hint: "<skill> [步骤号|标题片段]"
allowed-tools: ["Bash", "Read", "Write", "Edit", "Glob", "Grep"]
---

# Role: skill 定点调试执行器

`$ARGUMENTS` 的第一个 token 是 skill 名；其余（若有）是节点引用（步骤号，或标题片段）。**步骤号可以不给**——不给时进菜单模式，让用户在同一会话里选，省掉切浏览器看图。

## 步骤

1. **Read** `~/.claude/skills/skillviz/out/<skill>.flow.json`（不存在 → 告诉用户先用 **skillviz 技能**生成 `<skill>` 的流程图，停）。

2. **有没有第二个 token（节点引用）？**

   **没有（只给了 skill 名）→ 菜单模式：** 在当前会话打印一张编号菜单，每步一行：

   ```
   <id>  [<KIND>]  <title> — <summary 首句>
   ```

   `<KIND>` 取该步 `kind`（cli / llm / mixed）。`<summary 首句>` 只截第一句（到第一个句号/换行），菜单要一屏内可扫，深读留给流程图。菜单末行提示：`回一个数字或标题片段跑那一步，回 q 取消`。**打完就停，等用户下一条消息。** 把用户下一条**裸回复**当作节点引用——纯数字视作步骤号（约定：这一轮里回复的 `3` 就是 step 3，不是别的意思），文字视作标题片段——然后进第 3 步定位并执行。回 `q` / 空 → 取消，不跑任何步。

   **有 → 直达：** 按引用定位：数字 → 匹配 `steps[].id`；文字 → 匹配 `steps[].title` 或 substeps 标题片段。没匹配到 → 用上面同一张编号菜单列出全部步骤、停、**别瞎猜**节点（等用户回一个引用）。

3. **构造本次任务范围**，只来自命中的那一步（无论来自直达还是菜单回复，纪律完全一致——不因为它来自一条裸回复就绕过任何护栏）：
   - 前置假设：它之前步骤的产物已就绪（看该步 `inputs` 与上游 `outputs`），**不要**从头重跑整条 skill。
   - `kind` 为 cli/mixed → 跑该步 `commands`（`<占位符>` 先向上下文或用户确认实际值再跑）；为 llm → 按 `summary` + `substeps` 圈定的写作/判断任务执行，产出按 `outputs`。
   - 遵守该步 `failure_modes` 的处置指引；同时遵守 flow JSON `globals.guards` 里与本步相关的铁律。
   - 做完即停，不执行该步范围之外的内容。

4. **回报**：实际跑了哪些命令、产出/改动了哪些文件、与 `outputs` 是否一致、有无命中失败模式。

## 注意

- 这一步在**当前会话**里执行；若要干净环境隔离，提醒用户可先 `/clear` 再 `/dbg`。
- flow JSON 可能比 skill 的 .md 旧——若明显对不上（步骤号/命令变了），提醒用户让 **skillviz 技能**重新生成 `<skill>` 刷新，别按旧图硬跑。
- 这是 **skillviz 技能**（`~/.claude/skills/skillviz/`）的调试配套。想在图上定位再调，用 skillviz 出的 HTML；不想切浏览器，直接 `/dbg <skill>` 在会话里看菜单选。图上每步有两颗按钮：「复制 /dbg <skill> <id>」（直达那一步）和「复制 /dbg <skill>」（回会话出菜单再选）。
