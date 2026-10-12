# 运行、数据路径与排障

## 前置条件

- Python ≥3.10 与 `uv`；`wos_search_tsv.py` 通过 PEP 723 自动安装兼容的 `requests`（首次运行需可访问 PyPI），`merge_filter_jsonl.py` 只用标准库。
- WoS 接口后端已内置在 `scripts/wos_backend.py`，不依赖外部仓库、API key 或浏览器。
- 机构网络、校园网或机构 VPN 提供的 WoS 订阅授权。
- 命令中的 `$SKILL_DIR` 指本技能根目录：Claude Code 中即 `${CLAUDE_SKILL_DIR}`，其他代理替换为本技能目录的绝对路径；也可先切换到技能根目录再改用相对路径。
- TSV 的 `--outdir` 必须指向尚不存在的新目录；其父目录可以存在。每个查询使用独立目录，脚本只在整次任务通过校验后原子发布该目录。

## 临执行前探查权限

```bash
uv run "$SKILL_DIR/scripts/wos_search_tsv.py" --check-access
```

- `access: true`：继续；每会话一次即可。
- `access: false`：停止并让用户接入有授权的网络。不要反复探查。

## 只获取 WOSCC 命中数

```bash
uv run "$SKILL_DIR/scripts/wos_search_tsv.py" \
  --query '<完整 WoS 高级检索式>' --count-only
```

指定 `--editions` 时，count-only 返回的是 WOSCC 预过滤命中数；没有导出就无法给出 edition 后数量。

## JSON 快速路径

```bash
uv run "$SKILL_DIR/scripts/wos_search_tsv.py" \
  --query '<精确或窄检索式>' --format json --max 20
```

JSON 在线 smoke 已验证两条固定 DOI 可以一次返回 2/2 条。当前字段包括标题、作者、来源、年份、文献类型、WOSCC 被引次数、摘要、DOI 和 UT。

限制：JSON 当前不含作者关键词、Keywords Plus、卷期页、Z9、CR 和 `WE`。因此禁止与 `--editions` 联用；最多取 100 条，只用于快速档。

## TSV-first 标准/深入路径

```bash
uv run "$SKILL_DIR/scripts/wos_search_tsv.py" \
  --query '<检索式>' --format tsv --max 200 \
  --outdir '<会话临时目录>/wos' --prefix '<安全短名>'
```

限定 index：

```bash
uv run "$SKILL_DIR/scripts/wos_search_tsv.py" \
  --query '<检索式>' --format tsv --max 200 \
  --editions SCIE,ESCI \
  --outdir '<会话临时目录>/wos' --prefix '<安全短名>'
```

先用 count-only 得到 WOSCC 候选总数。若总数超过 `--max`，上述命令会以 `edition_requires_complete_export` 停止；应收窄查询或提高 `--max`。只有用户明确接受截断样本时才加：

```bash
--allow-truncated-edition
```

这只表示“在 WOSCC 排序前 N 条中后过滤”，不代表该 index 的完整结果或前 N 条。

- 默认 `fullRecord`，含关键词等完整字段。
- 需要 CR 时加 `--content fullRecordPlus`。
- 脚本导出 TSV、按 `WE` 后过滤，并生成供筛选使用的规范化 JSONL。
- `recordsFound` 是 WOSCC 命中；`retrievedRaw` 是原始取回；`retrieved` 是 edition 过滤后记录数。
- `editionScopeComplete` 表示是否在完整 WOSCC 候选集合上执行了 index 后过滤；为 `false` 时必须报告样本边界。

超过 1000 条时只有在用户确认后才加 `--allow-large`；单批仍为 1000，批间至少 1 秒，总量上限 100000。

## 网络和重试

- 禁止并发调用 WoS 接口。
- SID 过期导致 401/403 时，整次命令重新自举并重建查询；不要输出 SID。
- TLS 或暂时性连接失败最多重试整个命令一次；连续失败则停止。
- 非法检索式、授权缺失、字段结构变化属于不可盲重试错误。

## 多查询合并与确定性过滤

深入档的每个查询使用独立 `--outdir`。全部成功后再本地合并；此步骤不访问 WoS：

```bash
uv run "$SKILL_DIR/scripts/merge_filter_jsonl.py" \
  --input broad='<目录1>/broad_records.jsonl' \
  --input phrase='<目录2>/phrase_records.jsonl' \
  --outdir '<尚不存在的会话临时目录>/merged' \
  --year-min 2020 --year-max 2026 \
  --doc-types Article,Review --editions SCIE \
  --required-term '<字面必含词>' --excluded-term '<字面排除词>'
```

- 输入顺序决定首次出现的输出顺序；按 UT、其次规范化 DOI 去重，不做题名模糊合并。
- 年份、文献类型和 index 使用结构化字段精确过滤；必含词要求全部出现，排除词任一出现即排除，只做 Unicode 大小写折叠后的字面匹配。
- 输出 `merged_records.jsonl` 和 `merge_report.json`；报告输入数、去重数、各硬过滤原因和保留数。输出目录同样只在全部校验通过后原子发布。
- JSONL schema、稳定身份或身份映射冲突时失败关闭，不进入语义筛选。

## TSV 与规范化 JSONL

脚本按字段名解析 TSV，不依赖固定列数；兼容 UTF-8 BOM 与 CRLF。核心映射：

| JSONL | TSV |
|---|---|
| `title` | `TI` |
| `authors` | `AU` |
| `source` | `SO` |
| `year` | `PY` |
| `doc_type` | `DT` |
| `author_keywords` | `DE` |
| `keywords_plus` | `ID` |
| `abstract` | `AB` |
| `times_cited_woscc` | `TC` |
| `times_cited_all` | `Z9` |
| `doi` | `DI` |
| `ut` | `UT` |
| `cited_references` | `CR` |
| `wos_index` | `WE` |

## 排障

| 现象 | 处理 |
|---|---|
| `access: false` 或登录页错误 | 接入有授权的机构网络后重试 |
| 缺少 `requests` | 使用 `uv run` 运行脚本；不要绕过 PEP 723 |
| 无法加载 `scripts/wos_backend.py` | 技能文件不完整或被改动；恢复该文件后重试 |
| 未返回 `searchInfo` | 检查字段标签、括号、引号和布尔逻辑 |
| 导出不是 `text/plain` | 停止；WoS 接口可能变化，参照上游 wos-request 仓库的 `docs/wos_api_reference.md` 排查并同步 `wos_backend.py` |
| 缺少 `WE` | 无法执行 edition 限定；停止并报告 schema 变化 |
| 规范化数量与导出行数不符 | 不进入语义筛选，先修复数据完整性问题 |

接口细节的研发真相源是上游 wos-request 仓库的 `docs/wos_api_reference.md`（仅排障参考，运行不依赖该仓库）。中间产物放在会话临时目录；除非用户要求导出，否则不要复制到长期目录或向用户展示路径。
