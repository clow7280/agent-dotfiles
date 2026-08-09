# Zotero Local API 读取接口中文摘译

本文摘译自 Zotero 官方文档 [Basics](https://www.zotero.org/support/dev/web_api/v3/basics) 页面，归档版本和页面更新时间见[参考资料索引](README.md)。
本文只保留适用于只读 Local API 客户端的资源、响应格式、检索、排序、分页、缓存和状态码说明，省略 Web API 专用的远程认证、Atom 格式细节、速率限制和写入内容。
Local API 的明确差异以 [Local API 中文参考](local-api.md)为准；若译文与官方原文或实际行为不一致，以官方原文和实际测试结果为准。

## 资源

特定文献库的数据请求以 `/users/<userID>` 或 `/groups/<groupID>` 开头，以下统一记作 `<userOrGroupPrefix>`。
用户 ID 不同于用户名，群组 ID 也不同于群组名称。
群组 ID 可以通过 `/users/<userID>/groups` 获取；Local API 可使用的用户 ID 规则见 [Local API 中文参考](local-api.md)。

### 集合

| URI                                                           | 含义               |
| ------------------------------------------------------------- | ------------------ |
| `<userOrGroupPrefix>/collections`                             | 文献库中的全部集合 |
| `<userOrGroupPrefix>/collections/top`                         | 文献库中的顶层集合 |
| `<userOrGroupPrefix>/collections/<collectionKey>`             | 指定集合           |
| `<userOrGroupPrefix>/collections/<collectionKey>/collections` | 指定集合的子集合   |

### 条目

| URI                                                         | 含义                               |
| ----------------------------------------------------------- | ---------------------------------- |
| `<userOrGroupPrefix>/items`                                 | 文献库中的全部条目，不含回收站条目 |
| `<userOrGroupPrefix>/items/top`                             | 文献库中的顶层条目，不含回收站条目 |
| `<userOrGroupPrefix>/items/trash`                           | 回收站中的条目                     |
| `<userOrGroupPrefix>/items/<itemKey>`                       | 指定条目                           |
| `<userOrGroupPrefix>/items/<itemKey>/children`              | 指定条目的子条目                   |
| `<userOrGroupPrefix>/publications/items`                    | My Publications 中的条目           |
| `<userOrGroupPrefix>/collections/<collectionKey>/items`     | 指定集合中的条目                   |
| `<userOrGroupPrefix>/collections/<collectionKey>/items/top` | 指定集合中的顶层条目               |

### 保存的检索

| URI                                              | 含义                                                |
| ------------------------------------------------ | --------------------------------------------------- |
| `<userOrGroupPrefix>/searches`                   | 文献库中的全部保存的检索                            |
| `<userOrGroupPrefix>/searches/<searchKey>`       | 指定保存的检索                                      |
| `<userOrGroupPrefix>/searches/<searchKey>/items` | 执行指定保存的检索并返回匹配条目，仅 Local API 支持 |

Web API 仅提供保存的检索的元数据，Local API 还提供执行检索的第三个端点。

### 标签

| URI                                                              | 含义                             |
| ---------------------------------------------------------------- | -------------------------------- |
| `<userOrGroupPrefix>/tags`                                       | 文献库中的全部标签               |
| `<userOrGroupPrefix>/tags/<urlEncodedTag>`                       | 名称与指定值匹配的所有类型标签   |
| `<userOrGroupPrefix>/items/<itemKey>/tags`                       | 指定条目的标签                   |
| `<userOrGroupPrefix>/collections/<collectionKey>/tags`           | 指定集合中的标签                 |
| `<userOrGroupPrefix>/items/tags`                                 | 文献库中的标签，可根据条目筛选   |
| `<userOrGroupPrefix>/items/top/tags`                             | 顶层条目所使用的标签             |
| `<userOrGroupPrefix>/items/trash/tags`                           | 回收站条目所使用的标签           |
| `<userOrGroupPrefix>/collections/<collectionKey>/items/tags`     | 指定集合的条目所使用的标签       |
| `<userOrGroupPrefix>/collections/<collectionKey>/items/top/tags` | 指定集合的顶层条目所使用的标签   |
| `<userOrGroupPrefix>/publications/items/tags`                    | My Publications 条目所使用的标签 |

### 群组

`/users/<userID>/groups` 返回当前用户可访问的群组。
Local API 返回的群组元数据范围见 [Local API 中文参考](local-api.md)。

## 读取请求

本节中的参数均为可选参数。

### 通用格式参数

| 参数     | 值                                                            | Local API 默认值 | 含义                                           |
| -------- | ------------------------------------------------------------- | ---------------- | ---------------------------------------------- |
| `format` | `bib`、`json`、`keys`、`versions` 或[导出格式](#条目导出格式) | `json`           | 控制响应格式；`bib` 和导出格式只适用于条目请求 |

各格式的行为如下：

- `bib` 返回 XHTML 格式的参考文献表，最多处理 150 个条目。
- `json` 对多对象请求返回 JSON array，对单对象请求返回单个 JSON object。
- `keys` 对多对象请求返回以换行分隔的对象 key 列表，没有默认或最大数量限制。
- `versions` 适用于集合、条目和保存的检索的多对象请求，返回以对象 key 为键、对象 version 为值的 JSON object；它与 `keys` 一样没有默认或最大数量限制。
- 导出格式只适用于条目请求，并以指定格式生成响应。

Local API 不支持 `format=atom`，此类请求返回 `501 Not Implemented`。

### `format=json` 参数

| 参数      | 值                                                    | 默认值 | 含义                                                              |
| --------- | ----------------------------------------------------- | ------ | ----------------------------------------------------------------- |
| `include` | `bib`、`citation`、`data` 或[导出格式](#条目导出格式) | `data` | 指定响应包含的表示形式；多个值以逗号分隔，例如 `include=data,bib` |

`bib` 为每个条目返回一条格式化参考文献，`citation` 为每个条目返回一条格式化引文，`data` 返回 JSON 格式的全部可写字段。
这里的“可写字段”描述 JSON 的字段集合，并不表示当前 Local API 接受写请求。
导出格式只适用于条目请求，为每个条目返回相应格式的数据。

### 参考文献格式参数

以下参数适用于 `format=bib`、`include=bib` 和 `include=citation`：

| 参数       | 值      | 默认值                      | 含义                                                                            |
| ---------- | ------- | --------------------------- | ------------------------------------------------------------------------------- |
| `style`    | string  | `chicago-note-bibliography` | CSL style 的文件名，不含 `.csl` 扩展名，例如 `apa`；也可以是远程 CSL 文件的 URL |
| `linkwrap` | boolean | `0`                         | 设为 `1` 时，把 URL 和 DOI 返回为链接                                           |
| `locale`   | string  | `en-US`                     | 参考文献表的 locale；部分 style 固定使用某个 locale，无法本地化                 |

`format=bib` 返回按所选 style 规则排序的完整 XHTML 参考文献表。
`include=bib` 和 `include=citation` 则在各条目的 JSON `data` block 中返回单条格式化内容，整体结果仍按查询参数排序。
`format=bib` 处理请求所选的完整结果集，不考虑 `limit`，因此通常应只对集合或标签等范围明确的请求使用。

### 条目导出格式

以下值可作为条目请求的 `format` 或 `include` 参数：

| 参数                | 格式                                |
| ------------------- | ----------------------------------- |
| `bibtex`            | BibTeX                              |
| `biblatex`          | BibLaTeX                            |
| `bookmarks`         | Netscape Bookmark File Format       |
| `coins`             | COinS                               |
| `csljson`           | Citation Style Language data format |
| `csv`               | CSV                                 |
| `mods`              | MODS                                |
| `refer`             | Refer/BibIX                         |
| `rdf_bibliontology` | Bibliographic Ontology RDF          |
| `rdf_dc`            | Unqualified Dublin Core RDF         |
| `rdf_zotero`        | Zotero RDF                          |
| `ris`               | RIS                                 |
| `tei`               | Text Encoding Initiative            |
| `wikipedia`         | Wikipedia Citation Templates        |

## 检索

### 通用检索参数

| 参数       | 值                    | 默认值 | 含义                                                                                               |
| ---------- | --------------------- | ------ | -------------------------------------------------------------------------------------------------- |
| `itemKey`  | string                | 无     | 以逗号分隔的条目 key，仅适用于条目请求；单次最多指定 50 个条目                                     |
| `itemType` | [检索语法](#检索语法) | 无     | 按条目类型检索                                                                                     |
| `q`        | string                | 无     | quicksearch；默认检索标题和各 creator 字段，可用 `qmode` 更改模式；当前只支持 phrase search        |
| `since`    | integer               | `0`    | 只返回在指定 library version 之后修改的对象；version 来自先前响应的 `Last-Modified-Version` header |
| `tag`      | [检索语法](#检索语法) | 无     | 按标签检索                                                                                         |

Local API 接受相同的检索参数，但使用 Zotero 的本地 quicksearch 实现，因此相同 `q` 值得到的条目集合可能与 Web API 不完全一致。

### 条目端点参数

| 参数             | 值                               | 默认值                 | 含义                                               |
| ---------------- | -------------------------------- | ---------------------- | -------------------------------------------------- |
| `includeTrashed` | `0`、`1`                         | `0`，`/trash` 端点除外 | 是否包含回收站条目                                 |
| `qmode`          | `titleCreatorYear`、`everything` | `titleCreatorYear`     | quicksearch 模式；使用 `everything` 时包含全文内容 |

### 标签端点参数

| 参数    | 值                       | 默认值     | 含义                                          |
| ------- | ------------------------ | ---------- | --------------------------------------------- |
| `qmode` | `contains`、`startsWith` | `contains` | quicksearch 模式；`startsWith` 执行左边界匹配 |

### 条目范围内的标签端点参数

返回条目范围内的标签时，下列参数用于筛选条目。
主参数 `q`、`qmode` 和 `tag` 则用于筛选作为请求主要对象的标签。

| 参数        | 值                       | 默认值     | 含义                        |
| ----------- | ------------------------ | ---------- | --------------------------- |
| `itemQ`     | string                   | 无         | 与条目请求中的 `q` 相同     |
| `itemQMode` | `contains`、`startsWith` | `contains` | 与条目请求中的 `qmode` 相同 |
| `itemTag`   | [检索语法](#检索语法)    | 无         | 与条目请求中的 `tag` 相同   |

上述 `itemQMode` 值忠实保留归档原文。
2026 年 7 月对 Zotero 9.0.6 的实际测试显示，当前 Local API 实现把 `itemQMode` 用于条目 quicksearch，接受的值是 `titleCreatorYear` 与 `everything`。
客户端应以实际测试结果为准，并在 Zotero 升级后重新核对。

### 检索语法

`itemType` 和 `tag` 参数支持 Boolean search：

- `itemType=book` 表示类型为 `book`。
- `itemType=book || journalArticle` 表示逻辑 OR。
- `itemType=-attachment` 表示逻辑 NOT。
- `tag=foo` 表示标签为 `foo`。
- `tag=foo bar` 表示包含空格的单个标签。
- `tag=foo&tag=bar` 表示逻辑 AND。
- `tag=foo bar || bar` 表示逻辑 OR。
- `tag=-foo` 表示逻辑 NOT。
- `tag=\-foo` 表示首字符为连字符的字面量标签。

客户端或所使用的库有需要时，必须对检索字符串进行 URL 编码。

## 排序与分页

下列参数只适用于 `<userOrGroupPrefix>/items` 等多对象读取请求。
`format=bib` 请求不支持排序和分页。

| 参数        | 值                                                                                                                                                                                                                                               | Local API 默认值 | 含义                                                                           |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------- | ------------------------------------------------------------------------------ |
| `sort`      | `dateAdded`、`dateModified`、`title`、`creator`、`itemType`、`date`、`publisher`、`publicationTitle`、`journalAbbreviation`、`language`、`accessDate`、`libraryCatalog`、`callNumber`、`rights`、`addedBy`、`numItems`，其中 `numItems` 用于标签 | `dateModified`   | 排序字段                                                                       |
| `direction` | `asc`、`desc`                                                                                                                                                                                                                                    | 随 `sort` 而异   | 指定排序方向                                                                   |
| `limit`     | integer                                                                                                                                                                                                                                          | 无               | 限制单次请求返回的结果数；Local API 不设默认值或最大值，省略时返回全部匹配对象 |
| `start`     | integer                                                                                                                                                                                                                                          | `0`              | 第一条结果的 index，与 `limit` 一起选择结果切片                                |

显式使用 `limit` 和 `start` 时，Local API 仍提供分页，并在响应中包含 `Link` header。

### 结果总数

多对象读取响应包含自定义 HTTP header `Total-Results`，表示请求匹配的结果总数。
该值不是当前响应中实际返回的对象数。

### `Link` header

当匹配结果总数大于当前 `limit` 时，API 在 `Link` header 中提供分页链接。
可能的关系值为 `rel=first`、`rel=prev`、`rel=next` 和 `rel=last`，部分请求还会提供指向 Zotero 网站相关页面的 `rel=alternate` 链接。

## 缓存与增量读取

多对象请求返回 `Last-Modified-Version` header，其中包含当前 library version。
后续多对象读取请求可以发送 `If-Modified-Since-Version: <libraryVersion>`；如果文献库在该 version 后没有变化，API 返回 `304 Not Modified` 而不是 `200 OK`。
官方原文说明单对象条件请求目前尚未实现。

读取整个文献库时，客户端还应使用 `?since=<libraryVersion>`，只请求上次读取之后发生变化的对象。
条件请求在 Local API 中的工作方式与 Web API 相同，但本地响应的生成成本已经较低，因此客户端无需激进缓存。
对于大型本地文献库，`since` 是增量读取变更对象的首选方式。

## HTTP 状态码

| 状态码                      | 含义                                                                       |
| --------------------------- | -------------------------------------------------------------------------- |
| `200 OK`                    | `GET` 请求成功                                                             |
| `304 Not Modified`          | 条件读取的目标没有变化                                                     |
| `400 Bad Request`           | 请求参数或目标用户等信息无效                                               |
| `403 Forbidden`             | Local API 未在 Zotero 设置中启用                                           |
| `404 Not Found`             | 请求的资源不存在                                                           |
| `405 Method Not Allowed`    | 请求方法不受支持                                                           |
| `417 Expectation Failed`    | 请求携带了不受支持的 `Expect` header                                       |
| `500 Internal Server Error` | Zotero 内部错误                                                            |
| `501 Not Implemented`       | 请求 Atom、在 `/api/` 以外的端点请求非 3 API version，或请求其他未实现能力 |
| `503 Service Unavailable`   | 服务暂时不可用                                                             |

`/api/` 本身是版本探测端点，因此非 3 API version 对应的 `501` 规则不适用于该端点。
