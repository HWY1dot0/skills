# skillviz

**English** | [简体中文](README.zh-CN.md)

Turn a [Claude Code](https://claude.com/claude-code) skill or slash-command into a clickable, interactive flowchart of how it actually runs — each step, the commands it runs, its inputs/outputs, failure modes, and a one-click "debug just this step" handoff.

Not a skill (there's no `SKILL.md`) — it's a **slash-command plus a small Python renderer**, so it installs differently from the skills in this repo.

## How it works (v3)

The model understands, the renderer draws:

- **`/skillviz <name>`** — Claude reads the skill's `.md` (and any code it references), then writes a structured **flow JSON** describing each step in plain language: what it does, the commands it runs, inputs/outputs, failure modes, sub-steps.
- **`render_flow.py`** — deterministically renders that flow JSON into a single self-contained HTML flowchart. No markdown parsing, no guessing; the understanding already happened upstream.
- **`/dbg <name> [step]`** — reads the same flow JSON and runs a single step in your current session, or prints a numbered menu to pick one. Each step in the flowchart has a "copy `/dbg …`" button as the handoff.

## Install

```bash
git clone https://github.com/HWY1dot0/skills.git
cd skills/skillviz

# 1. Install the two slash-commands
cp commands/skillviz.md commands/dbg.md ~/.claude/commands/
```

The command files reference the author's path `~/Coding/Tools/skillviz/render_flow.py` (and its `out/` folder). Either clone this folder there, or edit that path in `commands/skillviz.md` and `commands/dbg.md` to wherever this folder lives.

Requires Python 3 — standard library only, no dependencies.

## Usage

```bash
# Generate + render a flowchart for a skill or command
/skillviz skill-selector
/skillviz path/to/some-skill.md

# Render an existing flow JSON yourself
python3 render_flow.py examples/skill-selector.flow.json --open
python3 render_flow.py examples/skill-selector.flow.json --lang en --open

# Debug one step in the current session
/dbg skill-selector        # numbered menu — reply a number
/dbg skill-selector 3      # jump straight to step 3
```

The **UI language** (section titles, buttons, hints) follows `--lang zh|en|auto` — `auto` reads the flow's `lang` field, default `zh`. The **content language** (each step's summary/title) is whatever language the flow itself was written in, chosen when it's generated.

## Example

Open `examples/skill-selector.html` in a browser to see a rendered flowchart — it visualizes this repo's own `skill-selector`. The flow JSON that produced it (`examples/skill-selector.flow.json`) sits alongside it.

## License

MIT.
