# skills

**English** | [简体中文](README.zh-CN.md)

Agent skills and tools for [Claude Code](https://claude.com/claude-code) and compatible runtimes.

## Skills

| Skill | What it does |
|---|---|
| [skill-selector](skill-selector/) | A skill for choosing skills: reuse / fork / compose / build decisions with multi-source search, a two-scanner security gate, blind-judged run-offs, and user-selectable cost modes (5k → 700k tokens). |

## Tools

| Tool | What it does |
|---|---|
| [skillviz](skillviz/) | Turn a skill or slash-command into a clickable, interactive flowchart of how it runs — with `/dbg` to run one step at a time. A slash-command plus a Python renderer, not a skill. |

## Install

Skills — symlink into your Claude Code skills directory:

```bash
git clone https://github.com/HWY1dot0/skills.git
ln -s "$(pwd)/skills/<skill-name>" ~/.claude/skills/<skill-name>
```

Tools install differently (e.g. slash-commands into `~/.claude/commands/`) — see each tool's own README, such as [skillviz](skillviz/).

Each skill and tool has its own README with details. MIT licensed.
