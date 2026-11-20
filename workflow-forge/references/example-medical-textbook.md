---
workflow:
  name: workflow-medical-ecg-textbook
  version: "1.0.0"
  domain: medical-education
  description: 把教材原文、临床指南与执医大纲整合成一份可追溯的跨学科心电图 PDF 讲义

  source_policy:
    primary: textbook            # 人卫版《诊断学》《内科学》《生理学》《病理学》
    secondary: clinical-guideline  # 心肌梗死心电图共识、报告规范化书写共识
    scope: exam-syllabus         # 执业医师资格考试大纲（心电图条目）
    anchor_required: true
    conflict_policy: side-by-side

  human_gates:
    - stage: authority-arbitrate
      condition: 每条涉及 ST 阈值、宽 QRS 鉴别要点、房室阻滞分度、报告术语的规则性陈述，均已对照指南原文逐条确认
      on_fail: halt
      reviewer: author
      evidence: gate_decision.json
    - stage: human-gate
      condition: pending 条目全部给出 confirmed / rejected / revise，且无一条被默认通过
      on_fail: halt
      reviewer: author
      evidence: gate_decision.json

  outputs:
    - format: pdf
      template: references/template-textbook-book.md
      destination: out/

stages:
  - name: source-index
    description: 锁定教材与指南的版次、出版年与文件哈希，避免后续页码锚点失稳
    input:
      - name: source_files
        type: files
        required: true
    agent_actions:
      - 逐本记录书名、版次、出版社、出版年、用途标签（primary / secondary / scope-definition）与 sha256
      - 对无法确认版次的文件标记 unverified 并向用户确认
    output:
      - name: sources
        type: json
        schema: sources.json
    human_gate: false
    fallback: 任一 primary 源版次无法确认时停止，向用户索取确切版次，不得以"最新版"代替

  - name: chunk-anchor
    description: 按章节切分语义完整片段，并附页码与字符区间锚点
    input:
      - name: sources
        type: json
        required: true
        from: source-index
    agent_actions:
      - 依据 source-index 的索引逐本切分，不切断定义句、不拆散表格
      - 每片写入 source_id、chapter、page、char_range
    output:
      - name: chunks
        type: jsonl
        schema: chunks.jsonl
    human_gate: false
    fallback: OCR 结果定位不可靠的片段标 low_confidence 并排除出引用池

  - name: entity-extract
    description: 按心电图领域 Schema 抽取征象、机制、解剖位点、判读标准与临床处置
    input:
      - name: chunks
        type: jsonl
        required: true
        from: chunk-anchor
    agent_actions:
      - 使用预定义实体类型 ecg_finding、mechanism、anatomical_site、criterion、clinical_action
      - 使用预定义关系 manifests_as、explained_by、localized_to、criterion_from
      - 抽取过程中不临时新增实体或关系类型
    output:
      - name: entities
        type: jsonl
        schema: entities.jsonl
      - name: relations
        type: jsonl
        schema: relations.jsonl
    human_gate: false
    fallback: 实体量异常时回退调整 Schema 粒度，不带着错误的抽取结果进入下游

  - name: cross-link
    description: 建立"征象→机制→解剖"的跨学科链接，把生理学与诊断学串起来
    input:
      - name: entities
        type: jsonl
        required: true
        from: entity-extract
      - name: relations
        type: jsonl
        required: true
        from: entity-extract
    agent_actions:
      - 沿 explained_by 与 localized_to 建立跨来源链接，例如 de Winter 征 → 左前降支近端闭塞 → 前壁
      - 每条链接记录两端 entity_id 与所用关系类型
    output:
      - name: cross_links
        type: jsonl
        schema: cross_links.jsonl
    human_gate: false
    fallback: 链接稀疏说明关系类型不足，回退 entity-extract 补齐后重跑

  - name: authority-arbitrate
    description: 对每条判读规则检索指南对应条目，教材与指南不一致时并排呈现，不自动裁决
    input:
      - name: cross_links
        type: jsonl
        required: true
        from: cross-link
      - name: guidelines
        type: files
        required: true
    agent_actions:
      - 只对涉及阈值、分度、术语口径的链接做仲裁，其余链接直接放行
      - 两侧原文各自附引文与定位，按 conflict_policy 给建议但不作最终判定
      - 找不到对应指南条目的条目标 unsourced 并单列，不编造条号或年份
    output:
      - name: arbitration_report
        type: text
        schema: arbitration_report.md
    human_gate: true
    fallback: 无法定位指南条目时保持 unsourced 并 halt，等待作者提供纸质版或补充来源

  - name: human-gate
    description: 逐条呈现待核项，收集 confirmed / rejected / revise 并落盘决策
    input:
      - name: arbitration_report
        type: text
        required: true
        from: authority-arbitrate
    agent_actions:
      - 每条待核项呈现教材原文、指南原文、冲突点与建议，便于作者一次判完
      - 将决策写入 gate_decision.json，记录核定人、时间戳与依据
      - 未决条目保持 pending，流程停在该阶段
    output:
      - name: gate_decision
        type: decision
        schema: gate_decision.json
    human_gate: true
    fallback: 超时未决时保持 pending 并 halt，不得默认通过

  - name: compose
    description: 按"判读入口→机制回溯→指南仲裁→临床决策"编排正文，每条陈述附来源定位
    input:
      - name: gate_decision
        type: decision
        required: true
        from: human-gate
      - name: cross_links
        type: jsonl
        required: true
        from: cross-link
    agent_actions:
      - 按章节结构编排正文，优先直接引用原文，仅添加过渡与组织语言
      - 每条实质性陈述后附来源定位（书名·版次·章节·页码，或指南名·年份·条目）
      - pending 条目只出现在待核区并显式标注，不得混入正文
    output:
      - name: draft
        type: text
        schema: draft.md
    human_gate: false
    fallback: 某节缺少已确认来源时留 [待补来源] 占位并列出缺口，不自由发挥

  - name: render
    description: 按教材版式渲染 PDF，保留脚注定位与插图原图号
    input:
      - name: draft
        type: text
        required: true
        from: compose
    agent_actions:
      - 调用 Pandoc + Eisvogel 模板或 workbuddy-docx 流程生成 PDF
      - 插图占位符替换为真实图像时保留原图号与页码，写入图注
    output:
      - name: final_pdf
        type: files
        schema: out/心电图跨学科讲义.pdf
    human_gate: false
    fallback: 模板或中文字体缺失时降级为无模板输出，并在交付说明中写明降级点

extensions:
  custom_stages: []
---

# 工作流：心电图跨学科讲义（实例）

> 本文件既是 `references/example-medical-textbook.md` 的可执行实例，
> 也是 `scripts/validate_workflow.py` 的自测样本。复制它时**改内容不改骨架**。

## 源策略

- **primary（事实骨架）**：人民卫生出版社《诊断学》第 10 版（万学红、卢雪峰主编）心电图篇、
  《内科学》循环系统疾病篇、《生理学》电生理章节、《病理学》心血管章节。
- **secondary（仲裁源）**：
  《心肌梗死心电图诊断标准和报告规范中国专家共识》、《心电图报告规范化书写专家共识（2026）》、
  《心电检查临床应用指南（2026 版）》。
- **scope（范围界定）**：执业医师资格考试大纲心电图相关条目。
- **冲突处理**：`side-by-side`。教材为教学可读性做过简化，指南针对具体问题高度精细化；
  两者不一致处必须并排标注差异，由作者定夺，**严禁 Agent 自行抹平**。

## 阶段 1 · source-index

- **输入**：教材与指南 PDF / 扫描件
- **动作**：建索引卡片，锁定版次与哈希；版次不确定标 `unverified`
- **输出**：`sources.json`
- **闸门**：否（索引结果须对作者可见）
- **回退**：版次不明即停，不接受"最新版"

## 阶段 2 · chunk-anchor

- **输入**：`sources.json`
- **动作**：按章节切分，附 `source_id` / `chapter` / `page` / `char_range`
- **输出**：`chunks.jsonl`
- **闸门**：否
- **回退**：低置信 OCR 片段标 `low_confidence`，排除出引用池

## 阶段 3 · entity-extract

- **输入**：`chunks.jsonl`
- **动作**：按 `ecg_finding` / `mechanism` / `anatomical_site` / `criterion` / `clinical_action`
  抽取实体，按 `manifests_as` / `explained_by` / `localized_to` / `criterion_from` 抽关系
- **输出**：`entities.jsonl`、`relations.jsonl`
- **闸门**：否（Schema 变更需确认）
- **回退**：实体量异常则回退调 Schema

## 阶段 4 · cross-link

- **输入**：`entities.jsonl`、`relations.jsonl`
- **动作**：建立跨学科链路，例：`de Winter 征 → explained_by → LAD 近端闭塞 → localized_to → 前壁/室间隔`
- **输出**：`cross_links.jsonl`
- **闸门**：否
- **回退**：链接稀疏则补关系类型

## 阶段 5 · authority-arbitrate（**闸门**）

- **输入**：`cross_links.jsonl` + 指南
- **动作**：仅对阈值/分度/术语类链接仲裁；两侧原文并排；不作最终判定
- **输出**：`arbitration_report.md`（每条 `pending | confirmed | rejected`）
- **闸门**：**是**，`on_fail: halt`
- **回退**：无对应条目则标 `unsourced` 并停，禁止编造条号

## 阶段 6 · human-gate（**闸门**）

- **输入**：`arbitration_report.md`
- **动作**：逐条核定，三态决策，落盘 `gate_decision.json`
- **输出**：`gate_decision.json`
- **闸门**：**是**（本阶段即闸门）
- **回退**：超时保持 `pending` 并停

## 阶段 7 · compose

- **输入**：`gate_decision.json`、`cross_links.jsonl`
- **动作**：按「判读入口 → 机制回溯 → 指南仲裁 → 临床决策」编排；
  原文优先，每条陈述附来源定位；`pending` 条目不进正文
- **输出**：`draft.md`
- **闸门**：否（须逐条可回溯）
- **回退**：缺来源的节留 `[待补来源]` 占位

## 阶段 8 · render

- **输入**：`draft.md`
- **动作**：渲染 PDF，保留脚注与插图原图号
- **输出**：`out/心电图跨学科讲义.pdf`
- **闸门**：否
- **回退**：字体/模板缺失则降级并说明

## 改写指南

| 迁移到 | 需要改 | 可原样复用 |
|---|---|---|
| 心律失常章 | `entity-extract` 增加 `rhythm_origin`、`conduction_path`；`compose` 换结构模板 | 阶段 1、2、5、6、8 |
| 药理学跨系统 | 实体 Schema 换 `drug` / `target` / `adverse_effect`；secondary 换成药品说明书与药典 | 全部骨架阶段 |
| 病理切片判读 | `chunk-anchor` 的定位粒度由页码改为图像区域坐标；`render` 换图版模板 | 阶段 1、5、6 |
| 换输出为 DOCX | 只改 `workflow.outputs` 与 `render` 的调用命令 | 前 7 个阶段全部 |
