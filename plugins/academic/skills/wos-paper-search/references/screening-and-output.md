# 三态筛选与结果呈现

## 筛选输入

优先使用脚本生成的规范化 JSONL。每条记录至少包含：

```text
rank, ut, doi, title, authors, source, year, doc_type,
author_keywords, keywords_plus, abstract,
times_cited_woscc, times_cited_all, cited_references, wos_index
```

不要让筛选 worker 自行解析原始 TSV。先执行确定性规则：citation index、年份、文献类型、明确必含/排除词和重复 UT/DOI。只把需要语义判断的记录交给模型。

## 三态判定

每条记录严格返回：

```json
{
  "ut": "WOS:...",
  "doi": "10....",
  "title": "...",
  "status": "include | exclude | uncertain",
  "reason_codes": ["..."],
  "evidence": "仅引用题名、关键词或摘要中的一句依据"
}
```

- `include`：题名、关键词或摘要提供足够的正向相关证据，且不违反硬条件。
- `exclude`：存在明确冲突；必须给出可复核理由。
- `uncertain`：摘要缺失、标准边界模糊、信息互相冲突，或必须阅读全文才能判断。

不要为了得到二元结果而强迫 uncertain 条目入选或排除。建议理由码：

- `topic_mismatch`
- `method_mismatch`
- `population_or_context_mismatch`
- `year_or_type_mismatch`
- `missing_abstract`
- `insufficient_evidence`
- `full_text_required`

## 分片和合并

- 快速档由主代理直接核对，不启动筛选 worker。
- 标准/深入档按摘要总 token 量分片；约 25 条只是起始参考，不是硬规则。
- 先用一小片校准筛选标准，再并行余下分片。
- 每个输入 UT 必须恰好对应一个结果；拒绝缺失、重复或未知 UT。
- worker 完成顺序不得改变最终记录顺序。
- 对边界记录或 worker 之间不一致的记录统一标为 uncertain，由主代理复核。

## 研究进展综合

- 把“近期代表作”和“高被引基础作”分组。
- 每个研究现状、趋势或争议要点至少关联一篇支持论文。
- 只陈述摘要可以直接支持的内容；研究设计质量、样本细节、效应强度和因果结论若无摘要证据，标为需全文确认。
- 明确说明 WOSCC/订阅覆盖、摘要缺失、后过滤和截断带来的偏差。
- 被引次数是检索日期当天的快照，只用于描述传播情况。

## 默认交付模板

### 回答

先用一段话直接回答用户问题。研究进展任务可按现状、主要方法、共识/分歧和空白组织，但不要制造摘要没有支持的结论。

### 代表性论文

每篇列出：

```text
标题 — 首位作者 et al. — 来源 — 年份
WOSCC 被引：N（检索日） · DOI/UT
相关性：一句话
```

只在确有价值时单列 uncertain 项。

### 方法摘要

始终包含：

```text
检索日期：
Collection：WOSCC
Citation index：未限定 / SCI-EXPANDED / ESCI / ...
检索式、年份、文献类型：
命中 / 原始取回 / index 过滤后 / 筛选 / 入选 / 不确定：
排序与截断：
筛选依据：题名、关键词、摘要
局限：订阅覆盖、摘要缺失、后过滤、未核验全文
```

- 快速精确查询：未进行语义筛选时，把“筛选 / 入选 / 不确定”写为“不适用”。
- 纯导出：报告命中、取回、index 过滤后和去重数量；语义筛选相关项写为“不适用”。
- 多查询深入档：额外列出查询变体数、各式命中/取回、合并前记录数和按 UT/DOI 去重后的候选数。

模式 B 可以压缩措辞，但不得省略支持论文和方法摘要。用户未明确要求时，不提供 TSV、JSONL 或临时路径。
