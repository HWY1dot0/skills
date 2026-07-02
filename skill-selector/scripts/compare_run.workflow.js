// compare_run.workflow.js — Step 5 的"实跑对比"编排模板(Claude Code Workflow 脚本)。
//
// compare_candidates.py 只能聚静态可测的;这个模板补上它替不了的那步:
// 每个候选 × 每个测试用例 × repeats 遍,由独立 runner agent 只按该候选的
// SKILL.md 指导完成任务,再由**盲评 judge**(只见产物与标准,不见候选名)按
// Step 1 的 success criteria 裁决。产出 pass 矩阵 + 一致性(flaky 检测)。
//
// 用法(由主 agent 调用;workflow 脚本无文件系统访问,所以 cases/candidates
// 先由主 agent 读好、连同路径塞进 args):
//
//   Workflow({
//     scriptPath: "~/.claude/skills/skill-selector/scripts/compare_run.workflow.js",
//     args: {
//       candidates: [ { name: "pdf-form-filler", skillMdPath: "/abs/path/SKILL.md" }, ... ],
//       cases: [ { id: "c1", input: "把 fixtures/a.json 填进 fixtures/form.pdf",
//                  success_criteria: "输出 PDF 的 name/date 字段值与 JSON 一致,可开" }, ... ],
//       outDir: "/abs/path/compare-out",   // runner 产物根目录
//       repeats: 2,                         // 每组合跑几遍(≥2 才能测 flaky)
//     },
//   })
//
// 返回: { matrix: [{candidate, case, run, pass, note}], summary: [{candidate,
//         passed, total, flakyCases}], verdictHint }  → 主 agent 写进 decisions.md。

export const meta = {
  name: 'compare-candidate-skills',
  description: 'Run N candidate skills through a shared test set with blind judging (skill-selector Step 5)',
  whenToUse: 'After fetch/trust steps, when 2+ candidates survive and the winner must be decided by execution, not description.',
  phases: [
    { title: 'Run', detail: 'each candidate x case x repeat, isolated runner agents' },
    { title: 'Judge', detail: 'blind pass/fail per run against success criteria' },
  ],
}

// 成本参考:一个 runner ≈ 15-40k token、一个 judge ≈ 10-15k。3 候选×3 case×2 遍
// ≈ 600k;earlyStop(默认开)先跑 1 遍,赢家明显即停 ≈ 砍半。粗筛用 2 case×1 遍起步。
const { candidates, cases, outDir, repeats = 2, earlyStop = true } = args
if (!candidates?.length || !cases?.length || !outDir) {
  throw new Error('args 需要 candidates[], cases[], outDir(绝对路径)')
}

// 盲评匿名化:judge 只见 runId(字母),不见候选名。映射只在本脚本与返回值里。
const anon = {}
candidates.forEach((c, i) => { anon[c.name] = String.fromCharCode(65 + i) })

const RUN_SCHEMA = {
  type: 'object',
  properties: {
    did: { type: 'string', description: 'What was done, step by step, terse' },
    artifacts: { type: 'array', items: { type: 'string' }, description: 'Absolute paths of outputs written' },
    blocked: { type: 'boolean', description: 'true if the skill could not complete the case' },
    blockReason: { type: 'string' },
  },
  required: ['did', 'artifacts', 'blocked'],
}

const JUDGE_SCHEMA = {
  type: 'object',
  properties: {
    pass: { type: 'boolean' },
    note: { type: 'string', description: 'One line: why pass/fail, citing concrete evidence' },
  },
  required: ['pass', 'note'],
}

// Runner:只准用该候选的 SKILL.md 当指导,产物落匿名目录(为盲评)
const runStage = j => agent(
  `You are executing ONE candidate skill on ONE test case, as part of a controlled comparison.\n\n` +
  `Read this skill definition first and follow ONLY its guidance (its scripts/references included; ` +
  `do not draw on other skills you may know): ${j.cand.skillMdPath}\n\n` +
  `Task (the test case): ${j.cs.input}\n\n` +
  `Write every output artifact under: ${outDir}/${anon[j.cand.name]}/${j.cs.id}-r${j.r}/ (create it). ` +
  `If the skill's guidance cannot complete this case, stop and report blocked=true — do NOT improvise ` +
  `beyond the skill's instructions; the point is measuring the skill, not you.`,
  { label: `run:${j.cand.name}/${j.cs.id}#${j.r}`, phase: 'Run', schema: RUN_SCHEMA },
)

// Judge:盲评 —— 只给匿名产物与标准,不给候选名;宁严勿宽
const judgeStage = (runOut, j) => {
  if (!runOut) return { ...j, verdict: { pass: false, note: 'runner died/skipped' }, runOut: null }
  if (runOut.blocked) return { ...j, verdict: { pass: false, note: `blocked: ${runOut.blockReason || 'skill guidance insufficient'}` }, runOut }
  return agent(
    `You are a strict, skeptical grader in a blind comparison. You do NOT know which tool produced ` +
    `this output — judge only the evidence.\n\n` +
    `Success criteria: ${j.cs.success_criteria}\n\n` +
    `The runner reported doing: ${runOut.did}\n` +
    `Artifacts to inspect (Read them, do not trust the report): ${runOut.artifacts.join(', ') || '(none)'}\n\n` +
    `Default to pass=false unless the artifacts demonstrably satisfy the criteria. Cite what you checked.`,
    { label: `judge:${j.cs.id}`, phase: 'Judge', schema: JUDGE_SCHEMA },
  ).then(v => ({ ...j, verdict: v, runOut }))
}

// 第一轮:每组合 1 遍。earlyStop 时赢家明显就不跑后续 repeats(典型省 ~50% token)。
const round1 = []
for (const cand of candidates) for (const cs of cases) round1.push({ cand, cs, r: 1 })
log(`第一轮:${candidates.length} 候选 × ${cases.length} 用例 × 1 遍 = ${round1.length} 组合`)
let results = await pipeline(round1, runStage, judgeStage)

const rate = name => {
  const mine = results.filter(Boolean).filter(x => x.cand.name === name)
  return mine.length ? mine.filter(x => x.verdict.pass).length / mine.length : 0
}
const r1rank = candidates.map(c => ({ c, rate: rate(c.name) })).sort((a, b) => b.rate - a.rate)
const decisive = r1rank.every(x => x.rate === 0) ||                       // 全军覆没 → build
  (r1rank[0].rate >= 0.75 && (r1rank.length < 2 || r1rank[0].rate - r1rank[1].rate >= 0.5))
let earlyStopped = false

if (earlyStop && decisive) {
  earlyStopped = true
  log(`第一轮已分胜负(${r1rank.map(x => `${x.c.name}:${(x.rate * 100).toFixed(0)}%`).join(' / ')}),跳过后续 repeats —— 注意:一致性(flaky)未测`)
} else if (repeats > 1) {
  // 胶着:只有与第一名差距 <0.5 的候选进入后续 repeats(掉队者不值得再花钱测)
  const contenders = r1rank.filter(x => r1rank[0].rate - x.rate < 0.5).map(x => x.c)
  const rest = []
  for (const cand of contenders) for (const cs of cases)
    for (let r = 2; r <= repeats; r++) rest.push({ cand, cs, r })
  log(`第二轮:${contenders.length} 个胶着候选加测至 ${repeats} 遍(+${rest.length} 组合)`)
  results = results.concat(await pipeline(rest, runStage, judgeStage))
}

// 汇总:矩阵 + 每候选通过率 + flaky(同 case 多遍结果不一致)
const matrix = results.filter(Boolean).map(x => ({
  candidate: x.cand.name, case: x.cs.id, run: x.r,
  pass: x.verdict.pass, note: x.verdict.note,
}))
const summary = candidates.map(c => {
  const mine = matrix.filter(m => m.candidate === c.name)
  const byCase = {}
  mine.forEach(m => { (byCase[m.case] ??= []).push(m.pass) })
  const flakyCases = Object.entries(byCase).filter(([, v]) => new Set(v).size > 1).map(([k]) => k)
  return { candidate: c.name, passed: mine.filter(m => m.pass).length, total: mine.length, flakyCases }
})
summary.sort((a, b) => (b.passed / b.total) - (a.passed / a.total) || a.flakyCases.length - b.flakyCases.length)

const best = summary[0]
let verdictHint = !best || best.passed === 0
  ? 'No candidate cleared any case — this justifies BUILD (Step 4); the matrix shows exactly which cases a new skill must pass.'
  : `Leader: ${best.candidate} (${best.passed}/${best.total}${best.flakyCases.length ? `, flaky on ${best.flakyCases.join(',')}` : ''}). ` +
    'Adopt if it also passed the trust gate; near-misses with complementary case coverage → consider compose.'
if (earlyStopped) verdictHint += ' [early-stopped after round 1 — consistency/flakiness NOT measured; re-run with earlyStop:false if the task is high-stakes]'

return { matrix, summary, verdictHint, earlyStopped, anonMap: anon }
