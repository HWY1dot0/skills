# skills

[English](README.md) | **简体中文**

给 [Claude Code](https://claude.com/claude-code) 及兼容运行时的 agent skill 与工具集。

## Skills

| Skill | 干什么的 |
|---|---|
| [skill-selector](skill-selector/README.zh-CN.md) | 挑 skill 的 skill：复用 / fork / 组合 / 自建的决策流水线——多源搜索、双扫描器安全门、盲评实跑对比、用户自选的成本档位（5k → 700k token）。 |

## Tools

| 工具 | 干什么的 |
|---|---|
| [skillviz](skillviz/README.zh-CN.md) | 把一个 skill 或斜杠命令画成可点击的交互式流程图——配 `/dbg` 只跑其中一步。是斜杠命令 + Python 渲染器，不是 skill。 |

## 安装

Skill——symlink 进你的 Claude Code skills 目录：

```bash
git clone https://github.com/HWY1dot0/skills.git
ln -s "$(pwd)/skills/<skill-name>" ~/.claude/skills/<skill-name>
```

工具装法不同（比如斜杠命令要放进 `~/.claude/commands/`）——详见各工具自己的 README，例如 [skillviz](skillviz/README.zh-CN.md)。

各 skill 与工具详见其目录内 README。MIT 协议。
