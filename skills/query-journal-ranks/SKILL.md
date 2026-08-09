---
name: query-journal-ranks
description: 通过 easyScholar 开放 API 查询并解释期刊等级、SCI 与 SSCI 的 JCR 分区、中科院分区、影响因子、核心目录、院校榜单与自定义数据集。用户提及期刊分区、期刊等级、SCI、SSCI、中科院分区、JCR、影响因子或 easyScholar 时使用。
---

# 查询期刊等级与分区

调用 easyScholar 开放接口，保留原始数据集语义，并将自定义等级编码解码为可读结果。
使用附带脚本统一处理 URL 编码、密钥、限速和输出。

## 工作流

1. 确定期刊名，优先使用期刊官网名称或用户给出的完整刊名，不要把论文题名当作期刊名
2. 使用脚本内置的个人 easyScholar SecretKey，无需额外配置
3. 需要临时切换账户时，用环境变量 `EASYSCHOLAR_SECRET_KEY` 或 `--secret-key-file` 指定的单行密钥文件覆盖内置值
4. 运行 `scripts/query_journal_ranks.py`，脚本固定使用 HTTPS，并将请求起始间隔限制为至少 0.55 秒
5. 按查询时间报告结果，不自行补充 API 未返回的年份、版本或收录状态
6. 把“无返回等级”表述为“easyScholar 当前未返回匹配等级”，不得据此断言期刊未被某数据库收录

## 常用调用

在技能目录中运行：

```bash
python3 scripts/query_journal_ranks.py "Nature" "Accounting & Finance"
```

仅显示用户在 easyScholar 扩展端选中的数据集：

```bash
python3 scripts/query_journal_ranks.py --scope selected "Nature"
```

只保留关心的字段并输出结构化 JSON：

```bash
python3 scripts/query_journal_ranks.py \
  --fields sci,ssci,sciUp,sciUpSmall,sciUpTop,sciif \
  --format json "Nature"
```

从标准输入批量读取期刊名：

```bash
printf '%s\n' "Nature" "Cell" | python3 scripts/query_journal_ranks.py --stdin
```

## 选择与解释结果

- 默认 `--scope all`，用于完整查询；表格的“已选”列标识 `officialRank.select` 中的项目
- 只有用户明确要求“扩展端已选数据集”时才用 `--scope selected`，`select` 不是完整榜单
- 区分 `sci` 与 `ssci`，它们分别是 SCI 和 SSCI 的 JCR 分区；不要把缺少其中一个键解释为另一个键的否定结果
- 区分 `sciBase`、`sciUp`、`sciUpSmall` 和 `sciUpTop`，它们分别表达中科院基础版、升级版大类、升级版小类和升级版 Top 信息
- `customRank.rank` 已由脚本通过 `uuid&&&等级序号` 和 `rankInfo` 解码；未知 UUID 或未知等级序号必须保留原始值并显示警告，不得猜测
- 排名、影响因子与分区会变化，输出中注明查询日期；任务要求官方年份或历史版本时，说明此响应没有年份字段，并另行核验权威来源

需要解释全部字段、响应结构或排查解析问题时，读取 [references/api-schema.md](references/api-schema.md)。

## 错误处理

- `code != 200` 时报告 `code` 与 `msg`，不展示请求 URL 或密钥
- HTTP、TLS、超时或 JSON 解析失败时给出简短错误，并允许用户稍后重试，不要在高频循环中重试
- 精确刊名没有等级时，必要时只尝试一个可靠的标准缩写或全称变体，并继续遵守限速
- 多刊查询中部分失败时，保留成功项，逐项标记失败项
