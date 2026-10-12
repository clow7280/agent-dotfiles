---
name: zotero-local-api
description: 通过 Zotero 桌面客户端内置的只读 Local API（http://localhost:23119/api/）读取本地文献库：浏览与检索条目、集合、标签、保存的检索和群组，导出 BibTeX、CSL JSON、RIS 等格式，生成格式化参考文献，定位本地附件。当用户需要读取本地 Zotero 文献数据、检索本地文献元数据或从 Zotero 导出书目时使用。不读取 zotero.sqlite，不访问 Zotero Web API，不执行任何写入操作。
---

# Zotero Local API 使用指南

Zotero 桌面客户端在 `http://localhost:23119/api/` 提供 Zotero Web API v3 的只读本地实现。
用 `curl` 等 HTTP 工具直接发送 `GET` 请求即可读取本地文献库，不需要安装任何外部应用。
Local API 不访问网络、没有速率限制，也不需要认证。

## 前置条件与可用性检查

1. Zotero 桌面客户端正在运行
2. 已启用 Local API，设置路径为 Settings → Advanced → “Allow other applications on this computer to communicate with Zotero”

开始文献库工作前先探测一次：

```bash
curl -s -o /dev/null -w '%{http_code}' 'http://localhost:23119/api/users/0/items/top?limit=1'
```

- 返回 `200`: 服务可用，继续后续请求
- 连接被拒绝或超时: Zotero 未运行，请用户启动 Zotero 后重试
- 返回 `403`: Local API 未启用，请用户按上述设置路径开启
- 受限沙箱可能无法访问宿主机回环端口，此时先征得用户许可，再在沙箱外重试同一个只读请求

## 基本用法

- 只支持 `GET` 请求，当前不支持写请求，也不支持 Atom 格式
- 用户库前缀为 `/users/0`，`0` 代表当前本地用户；群组库前缀为 `/groups/<groupID>`，群组 ID 通过 `/users/0/groups` 获取
- 默认不分页，一次返回全部匹配结果；库较大时先用 `limit` 限制数量，需要翻页时配合 `start`
- 响应 header 中 `Total-Results` 是匹配总数，`Link` 提供翻页链接

常用端点如下，前缀记作 `<prefix>`：

| 端点                                | 内容                           |
| ----------------------------------- | ------------------------------ |
| `<prefix>/items`                    | 全部条目，不含回收站           |
| `<prefix>/items/top`                | 顶层条目，即文献本身           |
| `<prefix>/items/<itemKey>`          | 单个条目                       |
| `<prefix>/items/<itemKey>/children` | 条目的附件和笔记               |
| `<prefix>/collections`              | 全部集合                       |
| `<prefix>/collections/<key>/items`  | 集合内条目                     |
| `<prefix>/tags`                     | 全部标签                       |
| `<prefix>/searches/<key>/items`     | 执行保存的检索，Local API 独有 |
| `/users/0/groups`                   | 当前用户可访问的群组           |

常用查询参数：`q` 与 `qmode` 做快速检索，`itemType` 与 `tag` 支持布尔表达式过滤，`sort` 与 `direction` 控制排序，`since` 做增量读取。
完整的参数表、检索语法和状态码见 [references/read-requests.md](references/read-requests.md)。

## 常用请求示例

列出最近修改的 20 个顶层条目：

```bash
curl -s 'http://localhost:23119/api/users/0/items/top?sort=dateModified&direction=desc&limit=20'
```

按标题和作者快速检索，`q` 当前只支持短语匹配：

```bash
curl -s 'http://localhost:23119/api/users/0/items/top?q=deep%20learning&qmode=titleCreatorYear'
```

按条目类型和标签过滤：

```bash
curl -s 'http://localhost:23119/api/users/0/items/top?itemType=journalArticle&tag=machine-learning'
```

解析条目 JSON 时注意：

- 文献字段在每个元素的 `data` 内，例如 `data.title`、`data.publicationTitle`、`data.creators`
- `meta.creatorSummary` 和 `meta.parsedDate` 适合做列表摘要展示，二者都可能缺失
- `data` 的字段随条目类型和内容增减，空字段可能整体缺席，必须宽容解析
- 真实响应结构见 [references/response-samples.md](references/response-samples.md)，条目类型与字段的 schema 端点见 [references/types-and-fields.md](references/types-and-fields.md)

## 导出与附件定位

条目请求加 `format` 参数即可导出，支持 `bibtex`、`biblatex`、`csljson`、`ris`、`csv` 等格式：

```bash
curl -s 'http://localhost:23119/api/users/0/collections/<collectionKey>/items/top?format=bibtex'
```

生成格式化参考文献用 `format=bib`，`style` 指定 CSL 样式名：

```bash
curl -s 'http://localhost:23119/api/users/0/items/top?format=bib&style=apa&limit=10'
```

注意 `format=bib` 处理完整结果集且上限 150 条，不受 `limit` 约束，应只对集合或标签等范围明确的请求使用。
完整格式列表见 [references/read-requests.md](references/read-requests.md)。

仅当用户明确需要本地附件文件时，用 Local API 独有的 file 端点定位：

```bash
curl -s 'http://localhost:23119/api/users/0/items/<attachmentKey>/file/view/url'
```

该端点以纯文本返回附件的 `file://` URL；`/file` 和 `/file/view` 则返回 `302` 重定向。

## 约束与隐私

- Local API 不做身份认证，任何本地程序都能读取文献库；不得把端口 `23119` 转发或暴露给其他主机
- 文献库内容属于用户隐私；题名、标签、笔记、本地文件路径和真实用户 ID 不写入日志与诊断信息
- 不读取 `zotero.sqlite`，不访问 `api.zotero.org`，不尝试写请求
- Local API 与 Web API 的行为差异、版本探测和缓存规则见 [references/local-api.md](references/local-api.md)
