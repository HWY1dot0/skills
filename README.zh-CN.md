# skills

[English](README.md) | **简体中文**

给 [Claude Code](https://claude.com/claude-code) 及兼容运行时的 agent skill 集。

| Skill | 干什么的 |
|---|---|
| [skill-selector](skill-selector/README.zh-CN.md) | 挑 skill 的 skill：复用 / fork / 组合 / 自建的决策流水线——多源搜索、双扫描器安全门、盲评实跑对比、用户自选的成本档位（5k → 700k token）。 |
| [skillviz](skillviz/README.zh-CN.md) | 把一个 skill 或斜杠命令画成可点击的交互式流程图——渲染器自带打包，配一个 `/dbg` 命令只跑其中一步。 |

## 安装

```bash
git clone https://github.com/HWY1dot0/skills.git
ln -s "$(pwd)/skills/<skill-name>" ~/.claude/skills/<skill-name>
```

各 skill 详见其目录内 README（skillviz 另附一个配套的 `/dbg` 命令，见其 README）。MIT 协议。
