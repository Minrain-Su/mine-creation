# 标准阶段目录（Stage Catalog）

生成工作流时从这里选阶段、按任务逻辑排序，并为每阶段填入具体的输入输出契约。
**不要凭空发明阶段名**；确实没有合适原型时，在 `extensions.custom_stages` 声明并写理由。

每个阶段给出：`输入` / `Agent 动作` / `输出` / 默认闸门 / 失败回退。

---

## source-index：知识源清点与版本锁定

- **输入**：知识源文件列表（PDF / 网页 / 纸质扫描件 / 口述约束）
- **动作**：为每个源建立索引卡片，记录 `title`、`edition`、`year`、`publisher`、
  `role`（primary / secondary / scope-definition）、文件哈希。版本存疑的源标 `unverified`。
- **输出**：`sources.json`
- **默认闸门**：否（但索引结果必须对用户可见，让人有机会纠正版次）
- **失败回退**：源缺失或版本无法确认 → 停下询问，不要用"最新版"之类的模糊表述顶替

> 这一步的价值在于**锁定版次**。教材第 9 版和第 10 版页码、表述都不同，
> 不锁版本，后面所有锚点都是浮的。

---

## chunk-anchor：原文切片与定位锚点

- **输入**：`sources.json` 与对应源文件
- **动作**：按章节/小节切分为语义完整片段（不切断定义句、不把表格拆散）；
  每片附 `source_id`、`chapter`、`page`（或 `clause` / `paragraph`）、`char_range`。
- **输出**：`chunks.jsonl`
- **默认闸门**：否
- **失败回退**：OCR 质量差导致定位不可靠 → 标记 `low_confidence` 并排除出引用池，
  不要拿模糊文本充当原文

---

## entity-extract：实体与关系抽取

- **输入**：`chunks.jsonl` + 领域实体 Schema
- **动作**：按预定义 Schema 抽取实体与关系。Schema 必须**先定义后抽取**，
  不要在抽取过程中临时新增类型。
- **输出**：`entities.jsonl` + `relations.jsonl`
- **默认闸门**：否；但 **Schema 变更需人工确认**（Schema 一改，全库重抽，成本高）
- **失败回退**：实体量异常（过少或爆炸）→ 回退调 Schema 粒度，不要硬跑下游

---

## cross-link：跨来源/跨学科关系锚定

- **输入**：`entities.jsonl` + `relations.jsonl`
- **动作**：沿关系边建立跨来源链接，例如
  `征象 → explained_by → 机制`（跨诊断学与生理学）、
  `条款 → criterion_from → 规范`（跨法条与判例）。
  每条链接记录两端 `entity_id` 与所用 `relation`。
- **输出**：`cross_links.jsonl`
- **默认闸门**：否
- **失败回退**：链接稀疏（说明 Schema 关系类型不足）→ 回到 entity-extract 补关系类型

---

## authority-arbitrate：权威来源仲裁

- **输入**：`cross_links.jsonl` + secondary 源（指南 / 规范 / 标准）
- **动作**：对每条涉及"判读规则 / 阈值 / 标准 / 口径"的链接，检索 secondary 中的对应条目；
  primary 与 secondary 表述不一致时**并排呈现，不做自动裁决**；
  按 `conflict_policy` 给出建议（side-by-side / primary-wins / secondary-wins），
  最终由人工定夺。
- **输出**：`arbitration_report.md`，每条附
  `status: pending | confirmed | rejected`、两侧原文引文与定位
- **默认闸门**：**是，强制**
- **失败回退**：找不到对应 secondary 条目 → 标 `unsourced` 并列出，禁止编造条号或年份

> 这是整条链路的质量核心。共识往往比教材更细（例如按年龄性别分层的阈值），
> 教材为可读性做了简化。差异要**标出来**，不能抹平。

---

## human-gate：人类核定闸门

- **输入**：前一阶段输出 + 待核清单
- **动作**：逐条呈现待核项（原文、定位、冲突点、建议），等待
  `confirmed` / `rejected` / `revise`；`revise` 需附修改意见。
- **输出**：`gate_decision.json`，含每条决策、核定人、时间戳、依据
- **默认闸门**：是（本阶段即闸门）
- **失败回退**：超时未决 → 保持 `pending` 并 halt，不得默认通过

---

## compose：结构化编排与生成

- **输入**：已确认的 `cross_links`、`arbitration_report`、`gate_decision`
- **动作**：按目标结构编排正文（如"现象 → 机制 → 判读 → 决策"）；
  **每条实质性陈述附来源脚注**（`source_id` + 定位）；
  原文优先策略——直接引用优先，Agent 只添加过渡与组织语言；
  `pending` 条目不得进入正文，只能以显式标记出现在待核区。
- **输出**：`draft.md`
- **默认闸门**：否（但成品必须可逐条回溯）
- **失败回退**：某节缺少已确认来源 → 该节留 `[待补来源]` 占位并列出缺口，不要自由发挥

---

## render：输出物渲染

- **输入**：`draft.md` + 模板
- **动作**：调用渲染工具生成目标格式；保留脚注/边栏的定位信息，
  插图占位符替换为真实图像时**保留原图号与页码**。
- **输出**：最终文件（pdf / docx / markdown / png）
- **默认闸门**：否
- **失败回退**：模板或字体缺失 → 降级为无模板输出并说明降级点，不要静默换版式

---

# 阶段组合的常见骨架

| 场景 | 阶段序列 |
|---|---|
| 教材 + 指南 → 讲义/课本 | source-index → chunk-anchor → entity-extract → cross-link → authority-arbitrate → human-gate → compose → render |
| 论文综述（无需仲裁） | source-index → chunk-anchor → entity-extract → cross-link → compose → render |
| 规范符合性检查 | source-index → chunk-anchor → entity-extract → authority-arbitrate → human-gate（无 compose） |
| 数据→报告 | source-index → chunk-anchor → entity-extract → compose → render |

注意：只要出现 `authority-arbitrate`，后面必须跟 `human-gate`；`secondary: null` 时
不得出现该阶段。
