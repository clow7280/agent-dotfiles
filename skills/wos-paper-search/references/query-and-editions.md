# WOSCC 查询与 Citation Index 限定

## Collection 与 Citation Index

- `WOSCC` 是本技能唯一检索 collection，不等于 SCIE。
- 用户说“WoS/WOSCC”且未指定 index 时，检索其订阅可见的整个 WOSCC。
- 用户说“SCI”时规范化为 SCIE；用户说 SCIE、ESCI、SSCI、A&HCI 等时严格限定到指定 index。
- 当前适配器没有经过验证的服务端 edition 参数。不要使用或猜测 `ED=...`、`WE=...` 或请求体中的 `editions`。
- `ED` 在当前 WoS 高级检索中表示 Editor；`WE` 是 TSV 导出字段 `Web of Science Index`，不是已验证的查询字段。

## 可靠的后过滤规则

让脚本通过 TSV 的 `WE` 列执行后过滤。规范化以下别名：

| 用户输入 | `WE` 中的规范代码 |
|---|---|
| SCI、SCIE、SCI-E | `SCI-EXPANDED` |
| ESCI | `ESCI` |
| SSCI | `SSCI` |
| AHCI | `A&HCI` |
| CPCI-S | `CPCI-S` |
| CPCI-SSH | `CPCI-SSH` |
| BKCI-S | `BKCI-S` |
| BKCI-SSH | `BKCI-SSH` |

匹配 `WE` 文本括号内的代码集合；一条记录属于多个 index 时，只要与用户请求集合有交集即可保留。不要依赖可能本地化的完整英文名称。

后过滤不等价于服务端前置限定：

- 精确检索或小结果集：完整导出全部 WOSCC 命中后过滤。
- 大结果集：先按概念、年份和文献类型收窄到可完整导出的候选集合，再过滤。
- 默认情况下，脚本在 `recordsFound` 大于计划取回量时拒绝开始 edition 后过滤。先收窄查询或把 `--max` 提高到完整候选数。
- 只有用户明确接受样本时才传 `--allow-truncated-edition`；此时只能声称“在 WOSCC 排序前 N 条中按 index 过滤”，不能称为该 index 的前 N 条或完整结果。
- 方法摘要同时报告 WOSCC 原始命中数、原始取回数和 edition 过滤后数量。

## 常用高级检索字段

| 标签 | 含义 | 示例 |
|---|---|---|
| `TS` | 主题：题名、摘要、作者关键词、Keywords Plus | `TS=("ship trajectory" AND "deep learning")` |
| `TI` | 题名 | `TI=("attention is all you need")` |
| `AB` | 摘要 | `AB=(electrolyte*)` |
| `AU` | 作者 | `AU=(Zhang Y)` |
| `SO` | 来源出版物 | `SO=(Nature)` |
| `AK` | 作者关键词 | `AK=(graphene)` |
| `DO` | DOI | `DO=(10.1000/example)` |
| `UT` | WoS 入藏号 | `UT=(WOS:000000000000001)` |
| `PY` | 出版年份 | `PY=(2022-2026)` |
| `WC` | WoS 学科分类 | `WC=(Materials Science*)` |
| `DT` | 文献类型 | `DT=(Article OR Review)` |

使用 `AND / OR / NOT`、括号、引号和 `*` 通配符。不要把未经转义的用户原文直接拼进 shell；先构造完整 WoS 查询式，再作为单个参数传给脚本。

## 概念检索策略

把问题拆成概念组，每组内部使用同义词 `OR`，概念组之间使用 `AND`：

```text
TS=((概念A OR 同义词A1 OR 缩写A2) AND (概念B OR 同义词B1))
AND PY=(起始年-结束年)
```

快速/标准档优先一个可解释的主检索式。深入档可按以下顺序建立变体：

1. 高召回主题式；
2. 关键短语或方法限定式；
3. 必要时增加作者、期刊、学科或文献类型限定；
4. 记录每次变更、命中数和理由，避免无限随机收放。

多个变体分别导出并规范化后，使用 `scripts/merge_filter_jsonl.py` 按 UT、其次 DOI 去重；方法摘要报告每个变体的命中/取回、合并前条数和去重后候选数。

零命中时依次检查拼写、过窄短语、年份、文献类型和概念交集。命中过多时优先增加真正与研究问题有关的限定，而不是任意截断。

## 排序

- 精确查询：`relevance`。
- 代表性论文：先用 `relevance`，再结合被引信息识别基础工作。
- 最新研究进展：使用近年 `PY` 范围和 `date`。
- 不要把被引次数作为相关性或质量的唯一排序依据。
