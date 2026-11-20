---
# ============================================================
# 医学教材改编 plan 模板（Schema v2.1 ／ handbook 档）
# 用法：复制 → 替换 <> 占位符 → validate_workflow.py --strict
# 若做 3–8 页小册：depth 改 booklet、删 table-forge 与 pharm-bridge 两个阶段、
#   derived_blocks 只留 [bridge]，并把 require_tables / require_pharm_cross 删掉。
# ============================================================
workflow:
  name: workflow-example-handbook     # 改成本任务的 kebab-case 名，与文件名一致
  version: "2.1.0"
  domain: medical-education
  description: <以《内科学》哪一节为干，改成几页的什么>

  target:
    discipline: <internal-medicine>
    topic: <atrial-fibrillation>
    audience: student                 # student | resident | gp | specialist
    depth: handbook                   # booklet | handbook | reference
    page_budget:
      mode: ratio                     # ratio（相对原章节倍数）| absolute
      value: 5                        # ratio 时为倍数
      cap: 40
      target: 24                      # 目标总页数（含封面）
    structure:
      max_heading_level: 2
      heading_style: plain-noun       # 定义/病因/机制/表现/心电图/治疗
      toc: true
      derived_blocks: [bridge, table, flow, pharm-cross, editor-note, exam-point]
    require_tables: true              # V2.0 铁律 3：鉴别/分类/评分必须出表
    require_pharm_cross: true         # V2.0 铁律 4：治疗段必须有【药理交叉】

  source_policy:
    primary: "textbook:内科学第10版"
    secondary: "guideline:<现行指南名>"
    scope: exam-syllabus
    anchor_required: true
    conflict_policy: side-by-side
    page_offset_locked: true
    fidelity_target: 1.0

  invariants:
    - id: INV-1
      rule: 所有引文与教材原文逐字一致，删节只允许用"……"
      check: fidelity
      on_fail: halt
    - id: INV-2
      rule: 总页数不超过 page_budget.cap
      check: pages
      on_fail: rebuild
    - id: INV-3
      rule: 每条引文都带书名、版次与印刷页码
      check: quotes_with_page
      on_fail: halt
    - id: INV-4
      rule: 单页底部空白不超过 max_empty_mm
      check: empty_max_mm
      on_fail: rebuild
    - id: INV-5
      rule: 鉴别诊断/分类标准/评分系统一律成表，治疗流程一律成箭头流程
      check: tables
      on_fail: rebuild

  human_gates:
    - stage: authority-arbitrate
      condition: 每条阈值（评分切点/剂量/时间窗/目标值）均逐字对照现行指南，差异已并排列出
      on_fail: halt
      reviewer: domain-expert
      evidence: gate_decision.json
    - stage: human-gate
      condition: 全部待核条目已签字；未签项在正文保留【指南待核】虚框，不得静默删除
      on_fail: halt
      reviewer: author
      evidence: gate_decision.json

  outputs:
    - format: pdf
      template: assets/booklet.html
      destination: 课本/

budget:
  page: { w_mm: 210, h_mm: 297, margin_mm: [19, 19, 17, 19] }
  body: { size_pt: 10.0, line: 1.74 }
  quote: { size_pt: 9.7, line: 1.68 }
  page_content_mm: 261
  lines_per_page: 42
  chars_per_line: 49
  max_empty_mm: 40
  max_quote_count: 120

stages:
  - name: source-lock
    description: <清点教材、锁定版次、实测页码偏移>
    input:
      - { name: textbook_dir, type: files, required: true }
    agent_actions:
      - <逐本记录 page_count、版次、出版社>
      - <用目标章首页反推 offset = PDF 索引 − 印刷页>
      - <记录干教材该章印刷页起止，供页数预算>
    output:
      - { name: sources, type: json, schema: "{book, edition, page_count, offset, chapter_pages}" }
    asserts:
      - <每本书 offset 为实测整数；chapter_pages 可在 PDF 中打开验证>
    human_gate: false
    fallback: <版次无法确认则停下询问，不用同书其他版本顶替>

  - name: page-dump
    description: <逐页取文并打 PID 标记>
    input:
      - { name: sources, type: json, required: true, from: source-lock }
    agent_actions:
      - <对目标章±2 页逐页 get_text()，页首写 <<<PID 印刷页 >>>>
      - <图注、表题所在页标 has_figure / has_table>
    output:
      - { name: dump_files, type: files, schema: "dump/<book>_<topic>.txt" }
    asserts:
      - <任一 PID 标记后的文本可在 PDF 第 PID+offset 页原样找到>
    human_gate: false
    fallback: <OCR 质量差则标 low_confidence 并排除出引文池>

  - name: spine-extract
    description: <抽干教材定调句与原节顺序>
    input:
      - { name: dump_files, type: files, required: true, from: page-dump }
    agent_actions:
      - <找一句总括全章的定调句并记页码>
      - <抄下原节标题与顺序，作为唯一合法目录>
    output:
      - { name: spine, type: json, schema: "{thesis_quote, thesis_page, sections[], chapter_pages}" }
    asserts:
      - <定调句在 dump 中逐字命中，页码有 PID 支撑>
    human_gate: false
    fallback: <无单句定调则取节首第一个完整判断句，并在 plan 注明>

  - name: branch-bind
    description: <把《生理学》《病理学》《药理学》《组胚》的机制挂到干节点>
    input:
      - { name: spine, type: json, required: true, from: spine-extract }
    agent_actions:
      - <对每个干节点问"为什么"，只在枝教材中找到能回答的段落才挂>
      - <每条枝事实写 answers：它解释了哪个"为什么">
      - <挂不上的枝丢弃，不设延伸阅读兜底>
    output:
      - { name: bind, type: json, schema: "[{spine_node, branch_quote, book, page, answers}]" }
    asserts:
      - <每条 answers 非空且指向某个干节点；无孤儿枝>
    human_gate: false
    fallback: <枝不足时承认"教材未展开机制"，正文只留干引文>

  - name: quote-mint
    description: <造逐字引文库，标注干/枝>
    input:
      - { name: bind, type: json, required: true, from: branch-bind }
    agent_actions:
      - <整段复制原文，不改字；删节只把整句替换为"……">
      - <统一后缀：——引用于《书名》第N版 Pxxx>
      - <标 role: trunk|branch；单条 ≤180 字，超长拆条>
    output:
      - { name: quotes, type: jsonl, schema: "{id, text, book, edition, page, role, chars}" }
    asserts:
      - <按"……"分段，每段都能在对应 PID 页原文中命中（fidelity=1.0）>
    human_gate: false
    fallback: <命中失败先查全半角/连字符/下标，仍失败整条弃用，不改字>

  - name: table-forge
    description: <鉴别诊断/分类标准/评分系统转表格，治疗流程与病理演变转箭头流程>
    input:
      - { name: quotes, type: jsonl, required: true, from: quote-mint }
    agent_actions:
      - <扫描鉴别诊断、分类标准、评分系统三类，逐类落表：列=对比维度，行=疾病/类别/条目>
      - <治疗流程、病理演变落成 A → B → C 箭头流程，必要时带回环>
      - <表格单元格只用教材关键词，不写新事实；表下注明书名版次页码>
    output:
      - { name: tables, type: json, schema: "{id, kind: table|flow, columns[], rows[][], flow[], source}" }
    asserts:
      - <每个表 ≥2 列 2 行；每个流程 ≥3 个节点；均可追到引文 id>
    human_gate: false
    fallback: <教材无鉴别表时只抽教材列出的鉴别点做表；无流程时用原文顺序连箭头并注明>

  - name: pharm-bridge
    description: <治疗章节设【药理交叉】，写清靶点→电生理/生化结果→临床结果>
    input:
      - { name: quotes, type: jsonl, required: true, from: quote-mint }
    agent_actions:
      - <每药一块：微观靶点（阻滞K⁺通道/抑制COX-1/阻断β受体）>
      - <接中间结果（延长APD/减慢房室传导/减少TXA₂）与宏观结果（维持窦律/控率/抗血小板）>
      - <靶点与结果均用教材原文用词>
    output:
      - { name: pharm, type: json, schema: "{drug, target, mechanism, outcome, source}" }
    asserts:
      - <每块 target/mechanism/outcome 三栏非空且页码可反查>
    human_gate: false
    fallback: <教材未讲靶点则只写结果，靶点栏填"教材未述"，不得用模型记忆补>

  - name: authority-arbitrate
    description: <阈值类陈述的指南仲裁>
    input:
      - { name: quotes, type: jsonl, required: true, from: quote-mint }
    agent_actions:
      - <抽全部阈值：评分切点、剂量、时间窗、适应证>
      - <查现行指南并记名称/年份/条目号；不一致时并排呈现，不自动裁决>
    output:
      - { name: arbitration, type: json, schema: "{item, textbook_value, guideline_value, agree, pending}" }
    asserts:
      - <每条 pending 项在正文有对应【指南待核】标记>
    human_gate: true
    fallback: <指南不可得则保留待核标记、签署表留空并 halt>

  - name: human-gate
    description: <逐条签字>
    input:
      - { name: arbitration, type: json, required: true, from: authority-arbitrate }
    agent_actions:
      - <逐条呈现原文/定位/差异/建议，等待 confirmed|rejected|revise>
    output:
      - { name: gate_decision, type: decision, schema: "{id, status, reviewer, date, note}" }
    asserts:
      - <无 pending 残留>
    human_gate: true
    fallback: <超时保持 pending 并 halt，不默认通过>

  - name: budget-plan
    description: <按容量模型反推每页块数与字号>
    input:
      - { name: spine, type: json, required: true, from: spine-extract }
      - { name: quotes, type: jsonl, required: true, from: quote-mint }
      - { name: tables, type: json, required: true, from: table-forge }
    agent_actions:
      - <按 typography-recipes 算 line_mm / lines_per_page / chars_per_line>
      - <累加引文、表格、流程、药理块、图的块高，Σ ≤ pages×261×0.96>
      - <超限先调字号 0.3pt，再砍枝引文>
    output:
      - { name: budget, type: json, schema: "schema.budget 段" }
      - { name: outline, type: json, schema: "{sections[], per_section_quotes, dropped[]}" }
    asserts:
      - <块高总和 ≤ pages×content_mm×0.96>
    human_gate: false
    fallback: <算不下按删除优先级删，并把 dropped 记入 outline>

  - name: condense
    description: <按逻辑链编排：临床锚定→机制回溯→诊断鉴别→决策药理>
    input:
      - { name: outline, type: json, required: true, from: budget-plan }
      - { name: quotes, type: jsonl, required: true, from: quote-mint }
      - { name: tables, type: json, required: true, from: table-forge }
      - { name: pharm, type: json, required: true, from: pharm-bridge }
    agent_actions:
      - <节序固定：临床定义/病因→基础机制→临床表现/心电图→诊断鉴别→治疗决策与药理>
      - <标题降为名词短语；每节：干引文→枝引文(0-3)→表/流程(如需)→串讲一句>
      - <引文附（——引用于《》第N版 Pxxx）；治疗段插入【药理交叉】块>
    output:
      - { name: draft, type: text, schema: "draft.md（{{Q:id}}/{{T:id}}/{{P:id}}/{{FIG:n}}）" }
    asserts:
      - <引文数 ≤ max_quote_count；标题为名词短语；表与药理块均已落位>
    human_gate: false
    fallback: <仍超页回 budget-plan 重算，不在排版阶段偷改字号>

  - name: typography-compose
    description: <按 budget 生成印刷版式 HTML>
    input:
      - { name: draft, type: text, required: true, from: condense }
      - { name: template, type: files, required: true }
    agent_actions:
      - <复制 assets/booklet.html，把 CSS 变量换成 budget 数值>
      - <干引文深蓝、枝引文金色；表格用三线表；药理块三栏；封面单独满版>
    output:
      - { name: body_html, type: files, schema: "<book>_body.html" }
      - { name: cover_html, type: files, schema: "cover.html" }
    asserts:
      - <CSS 字号行高与 budget 一致；每张 img 有 width 与 figcaption>
    human_gate: false
    fallback: <字体缺失则记录回退字体链并告知，不静默换版式>

  - name: pdf-render
    description: <渲染、合并封面、盖页码、写书签>
    input:
      - { name: body_html, type: files, required: true, from: typography-compose }
      - { name: cover_html, type: files, required: true, from: typography-compose }
    agent_actions:
      - <无头 Chromium 打印两个 HTML；PyMuPDF 合并；封面不编号>
      - <按 h2 写二级书签，写 title/author/keywords>
    output:
      - { name: final_pdf, type: files, schema: "课本/<书名>.pdf" }
    asserts:
      - <pages == budget.target ±1；bookmarks ≥ 节数+1>
    human_gate: false
    fallback: <目标被占用则另存带后缀副本并如实报告>

  - name: metric-audit
    description: <跑机器审计：页数/空白/引文/表格/药理/保真>
    input:
      - { name: final_pdf, type: files, required: true, from: pdf-render }
      - { name: plan, type: files, required: true }
    agent_actions:
      - <跑 scripts/audit_pdf.py <pdf> --plan <plan> --dump dump/ --json>
      - <empty_max_mm 超标回排版；fidelity<1 回 quote-mint；tables 不足回 table-forge>
    output:
      - { name: audit_report, type: json, schema: "{pages, quotes, tables, pharm_cross, fidelity, pass}" }
    asserts:
      - <pass == true>
    human_gate: false
    fallback: <不达标即 rebuild，不交付未过审的 PDF>

qa_checks:
  - { id: QA-1, desc: 引文逐字保真, expr: fidelity, op: ">=", value: 0.999, on_fail: halt }
  - { id: QA-2, desc: 单页底部空白, expr: empty_max_mm, op: "<=", value: 40, on_fail: rebuild }
  - { id: QA-3, desc: 引文条数, expr: quotes, op: ">=", value: 40, on_fail: rebuild }
  - { id: QA-4, desc: 引文均带页码, expr: quotes_with_page, op: ">=", value: 40, on_fail: halt }
  - { id: QA-5, desc: 表格数量（鉴别/分类/评分）, expr: tables, op: ">=", value: 3, on_fail: rebuild }
  - { id: QA-6, desc: 药理交叉模块, expr: pharm_cross, op: ">=", value: 1, on_fail: rebuild }
  - { id: QA-7, desc: 总页数上限, expr: pages, op: "<=", value: 40, on_fail: rebuild }
  - { id: QA-8, desc: 枝引文占比（干支平衡）, expr: role_mix, op: ">=", value: 0.2, on_fail: warn }

extensions:
  custom_stages: []
---

# <书名>　改编说明

## 一、这本书回答什么

<以《内科学》第N版"X"节为干，向《生理学》《病理学》《药理学》《组织学与胚胎学》
借 N 条机制，把 M 页原节改成 P 页手册。>

## 二、逻辑链（V2.0 铁律 1）

```
临床定义/病因（干） → 基础机制/病理（枝） → 临床表现/心电图（干）
→ 诊断与鉴别（干＋表格） → 治疗决策（干）＋药理交叉（药理枝）
```

## 三、容量算式

```
line_mm        = <10.0 × 1.74 × 0.3528> = <6.14>
lines_per_page = ⌊261 / <6.14>⌋ = <42>
chars_per_line = ⌊172 / (9.7 × 0.3528)⌋ = <50>
可用高度       = <pages−1> × 261 × 0.96 = <…> mm
```

## 四、图表清单（铁律 3）

| 编号 | 类型 | 内容 | 来源 |
|---|---|---|---|
| 表 1 | table | <鉴别诊断：X vs Y vs Z> | <《内科学》第10版 Pxxx> |
| 表 2 | table | <评分系统> | <…> |
| 图 1 | flow | <治疗流程> | <…> |

## 五、药理交叉清单（铁律 4）

| 药 | 微观靶点 | 中间结果 | 宏观结果 | 来源 |
|---|---|---|---|---|
| <胺碘酮> | <阻滞K⁺通道> | <延长APD> | <维持窦律> | <《药理学》第10版 Pxxx> |

## 六、待核（铁律 5）

<列阈值条目，签字后才渲染终稿。>

## 七、改写指南

| 变化 | 改什么 | 不变 |
|---|---|---|
| 换疾病 | target.topic、定调句、quotes | 14 个阶段 |
| 换档位 | page_budget、derived_blocks、require_* | 引文库与渲染链 |
