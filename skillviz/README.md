# skillviz

**English** | [简体中文](README.zh-CN.md)

A [Claude Code](https://claude.com/claude-code) **skill** that turns a skill or slash-command into a clickable, interactive flowchart of how it actually runs — each step, the commands it runs, its inputs/outputs, failure modes, and a one-click handoff to debug a single step.

It auto-activates: ask "visualize how skill-selector works" / "画出 cpi 的流程" / "skillviz cpi" and it fires — you don't invoke it by name. It bundles its own renderer (`render_flow.py`) and ships a companion `/dbg` command for stepping through a flow.

## How it works (v3)

The model understands, the renderer draws:

- **The skill** — reads the target skill's `.md` (and any code it references), then writes a structured **flow JSON** describing each step in plain language: what it does, the commands it runs, inputs/outputs, failure modes, sub-steps.
- **`render_flow.py`** — deterministically renders that flow JSON into a single self-contained HTML flowchart. No markdown parsing, no guessing; the understanding already happened upstream. Bundled inside the skill, so there's no path to configure.
- **`/dbg <name> [step]`** (companion command) — reads the same flow JSON and runs a single step in your current session, or prints a numbered menu to pick one. Each step in the flowchart has a "copy `/dbg …`" button as the handoff.

## Install

```bash
git clone https://github.com/HWY1dot0/skills.git
cd skills

# The skill (symlink into your Claude Code skills directory)
ln -s "$(pwd)/skillviz" ~/.claude/skills/skillviz

# The companion /dbg command
cp skillviz/commands/dbg.md ~/.claude/commands/
```

Requires Python 3 — standard library only, no dependencies. The renderer lives inside the skill, so nothing else to wire up.

## Usage

```bash
# Just ask — the skill auto-activates. No slash-command to remember:
#   "visualize how skill-selector works"   "画出 cpi 的流程"   "skillviz cpi"

# Render an existing flow JSON yourself (from this folder)
python3 render_flow.py examples/skill-selector.flow.json --open
python3 render_flow.py examples/skill-selector.flow.json --lang en --open

# Debug one step in the current session (companion command)
/dbg skill-selector        # numbered menu — reply a number
/dbg skill-selector 3      # jump straight to step 3
```

The **UI language** (section titles, buttons, hints) follows `--lang zh|en|auto` — `auto` reads the flow's `lang` field, default `zh`. The **content language** (each step's summary/title) is whatever language the flow itself was written in, chosen when it's generated.

## Example

Open `examples/skill-selector.html` in a browser to see a rendered flowchart — it visualizes this repo's own `skill-selector`. The flow JSON that produced it (`examples/skill-selector.flow.json`) sits alongside it.

## License

MIT.
