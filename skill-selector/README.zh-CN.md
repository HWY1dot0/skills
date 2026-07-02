# skill-selector

[English](README.md) | **简体中文**

**挑 skill 的 skill。** 给定一个任务，判断该*复用*现成的 agent skill、*fork* 一个改、把几个*组合*起来，还是*自建*——判断靠证据，入口有安全门，花多少 token 由你定。

适用于 [Claude Code](https://claude.com/claude-code) 及任何读 `SKILL.md` 的 agent 运行时。五个辅助脚本全是纯 Python 标准库——零依赖、不调 LLM、各自可独立运行。

## 为什么要有这个东西

agent skill 生态很大，也基本没人审。这套工具在建造和对真实生态实测（2026 年中）的过程中攒下四条教训，如今都固化进了流水线：

1. **star 会骗人。** 注册表常常指向埋在别人 monorepo 里的 vendored 副本（★0），而作者自己的仓库有几百星——有时注册表给的链接甚至已经 404。这里的每条线索都会先溯源到*作者的真仓库*、核对真实星数，才谈得上信任。
2. **"有脚本"不等于"脚本干活"。** 空壳 skill——函数直接返回硬编码常量、空函数体、`# Real implementation would…` 占位——光看描述和真货一模一样。信任扫描器专门抓这个。
3. **坏 skill 比没 skill 更糟。** skill 里既有模型会照做的指令，也有可能被执行的代码。按 NVIDIA 的研究口径，约 26% 的 skill 有漏洞、约 5% 疑似恶意。这里没有任何东西是不看内容就采用的。
4. **没有一家注册表做语义搜索。** 实测：同一个能力换三种说法，结果交集为零。所以召回和相关度只能在客户端自己保证——多源多变体撒网，加两级全文重排。

## 漏斗

```
grep decisions.md      Tier −1  这事以前决定过吗？                ~0 token
match_local.py         Tier 0   我本地是不是已经有了？             ~1k
fetch_candidates.py    Tier 2   多源搜索 + 下载进沙箱              ~2k
trust_scan.py          安全门    危险调用 / 注入 / 空壳？           几 k
compare_candidates.py  静态对比  并排评测卡                        ~1k
compare_run.workflow   实跑对比  盲评执行定胜负                    重(见下)
```

每一层的存在都是为了让选型尽早结束。多数选型应该停在 Tier 0——"你已经有了"。

## 档位——轻重由你选

| 档位 | 跑什么 | 约多少 token | 怎么触发 |
|---|---|---|---|
| **light** | 只查台账 + 本地匹配 | 2–5k | "快速看看"、"有没有现成的" |
| **standard**（默认） | + 多源搜索 + 信任门 + 静态对比 | 30–50k | ——什么都不说就是它 |
| **thorough** | + 候选间盲评实跑对比 | 150k–700k | "认真比一比"、"彻底对比" |

三条规则让成本可预期：

- **升档必须征得同意。** agent 永远不会不请自来地进入 thorough 档。静态证据分不出两个决赛选手时，它会停下来问你——选项带着价签——而不是默默烧掉 600k。
- **降档永远免费。** 任何档位下，本地一查就有强匹配，5k 收工。档位定的是天花板，不是地板。
- **无头运行永不自动升档。** 没人能点头，就没有实跑。

## 工具清单

| 组件 | 职责 |
|---|---|
| `SKILL.md` | agent 遵循的六步决策框架（要不要 → 定义任务 → 收集候选 → 打分 → 决策 → 实跑验证 → 记录） |
| `scripts/match_local.py` | 把*已装*的 skill 和斜杠命令按任务相关度排序。中英双语词法匹配 + 概念归一 + IDF 加权，跟随 symlink 安装。 |
| `scripts/fetch_candidates.py` | 多源搜索（SkillsMP + agentskill.work + `gh` 认证时的 GitHub **code search**——唯一搜 SKILL.md 正文的通道），仓库洪泛折叠、相关度优先排序、真源溯源、沙箱下载、全文重排。按配额头自我节流；把限流和死链分开标注。 |
| `scripts/trust_scan.py` | 确定性安全门：危险调用（AST 级）、网络+密钥外泄组合、注入式指令、零宽/双向控制字符、base64 blob、空壳检测——外加一份"哪些文件没扫到"的明示清单。`--baseline` 让复审只报新增。 |
| `scripts/compare_candidates.py` | 静态评测卡：信任判定、真代码 vs 空壳占比、依赖、有无示例。 |
| `scripts/compare_run.workflow.js` | thorough 档（Claude Code Workflow）：每个候选 × 用例 × 遍数在隔离 agent 中执行——只准按该候选自己的指导干活——然后由**盲评裁判**按你的成功标准打分。第一轮分出胜负即早停（省约一半）。返回 pass 矩阵 + 稳定性标记。 |
| `scripts/inventory_skills.py` | 裸列某目录下的所有 SKILL.md。 |
| `decisions.example.md` | 只增不改的决策台账模板——每记一条，下一次选型就更便宜（Tier −1）。 |

## 安全模型

两个扫描器，分工刻意不同：

- **`trust_scan.py`**（自带、零依赖、秒级）：每个下载候选都过的内联快闸。强项是*欺诈与质量*——空壳实现、隐藏字符、注入措辞——而且它会告诉你哪些没扫到，而不是沉默放行。
- **[NVIDIA SkillSpector](https://github.com/NVIDIA/SkillSpector)**（可选，推荐）：正式采用前的深扫——68 个模式 × 17 类、YARA 签名、CVE 查询、0–100 风险分。强项是*恶意*。

拿恶意样本对打过：注入/RLO/零宽两边都抓得到，但各自都抓到了对方漏掉的东西。所以两个都用：快闸扫一切，深扫留给你准备采用的那个。扫描器管不了的判断，见 `references/trust-and-safety-review.md`。

## 安装

```bash
git clone https://github.com/HWY1dot0/skills.git
ln -s "$(pwd)/skills/skill-selector" ~/.claude/skills/skill-selector
```

或者直接把目录拷进去。要求：Python 3.9+（仅标准库）。可选但推荐：认证过的 `gh` CLI（解锁 GitHub code search——唯一搜 SKILL.md *正文*的通道，并把 API 限额从 60/时提到 5000/时），以及做深扫的 SkillSpector。

试一下：

```bash
python3 scripts/match_local.py "fill pdf form"
python3 scripts/fetch_candidates.py "fill pdf form" "pdf form filler" --limit 5
python3 scripts/trust_scan.py ./candidates/<skill>
```

## 设计原则

- **脚本采集，agent 裁决。** 一切确定性的活（搜索、扫描、计数、排序）都是零 token 的 Python 脚本；agent 的 token 只花在判断上。这就是 light 档 5k 而不是 50k 的原因。
- **靠证据决策，不靠描述。** 描述是营销。信任门读代码，实跑对比执行代码，裁判盲评且默认不通过。
- **fail closed，且失败可见。** 扫描器报告自己的盲区；抓取器把限流标成"未验证"而不是"已死"；空手而归时会区分"配额耗尽"和"真的没有"。
- **制度记忆。** 每个决策往 git-ignore 的台账追加一行；下次选型先 grep 它，再谈全网搜索。

部分代码注释为中文（作者双语工作）；面向用户的文档中英双语。

## 协议

MIT
