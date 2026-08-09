# Zotero Local API 条目类型与字段中文摘译

本文摘译自 Zotero 官方文档 [Item Types and Fields](https://www.zotero.org/support/dev/web_api/v3/types_and_fields) 页面，归档版本和页面更新时间见[参考资料索引](README.md)。
本文只保留只读客户端需要的条目类型、字段和 creator type 元数据端点，省略面向写入客户端的 `/items/new` 模板端点。
若译文与官方原文或实际行为不一致，以官方原文和实际测试结果为准。

客户端需要知道哪些条目类型、字段和 creator type 组合有效时，可以从 API 读取这些 schema 元数据。
由于 schema 很少变化，官方文档建议客户端缓存类型和字段数据，例如缓存一小时。
后续请求可以携带首次响应中 `Last-Modified` header 的值作为 `If-Modified-Since` header；如果数据没有变化，服务端应返回 `304 Not Modified`，客户端可以继续使用缓存。
归档原文同时注明，这类 `If-Modified-Since` 条件请求尚未实现。

Web API 默认返回英文显示名称，并允许使用 `locale` 参数请求其他语言。
Local API 的本地化规则不同：它忽略 `locale`，根据 Zotero 用户的 locale 返回名称，而 `/api/creatorFields` 始终返回英文。
详情见 [Local API 中文参考](local-api.md)。

包含所有 locale 翻译的完整 schema 也可以从 <https://api.zotero.org/schema> 下载。
缓存方式和 schema 源码见 [`zotero-schema`](https://github.com/zotero/zotero-schema) 仓库。

## 获取全部条目类型

```http
GET /itemTypes
If-Modified-Since: Mon, 14 Mar 2011 22:30:17 GMT
```

响应示例：

```json
[
  { "itemType": "book", "localized": "Book" },
  { "itemType": "note", "localized": "Note" }
]
```

## 获取全部条目字段

```http
GET /itemFields
If-Modified-Since: Mon, 14 Mar 2011 22:30:17 GMT
```

响应示例：

```json
[
  { "field": "title", "localized": "Title" },
  { "field": "url", "localized": "URL" }
]
```

## 获取指定条目类型的全部有效字段

`itemType` 必须是有效条目类型。

```http
GET /itemTypeFields?itemType=book
If-Modified-Since: Mon, 14 Mar 2011 22:30:17 GMT
```

响应示例：

```json
[
  { "field": "title", "localized": "Title" },
  { "field": "abstractNote", "localized": "Abstract" }
]
```

## 获取指定条目类型的有效 creator type

`itemType` 缺失或无效时，请求返回 `400 Bad Request`。

```http
GET /itemTypeCreatorTypes?itemType=book
```

响应示例：

```json
[
  { "creatorType": "author", "localized": "Author" },
  { "creatorType": "editor", "localized": "Editor" }
]
```

## 获取 creator 字段

```http
GET /creatorFields
If-Modified-Since: Mon, 14 Mar 2011 22:30:17 GMT
```

响应示例：

```json
[
  { "field": "firstName", "localized": "First" },
  { "field": "lastName", "localized": "Last" },
  { "field": "name", "localized": "Name" }
]
```
