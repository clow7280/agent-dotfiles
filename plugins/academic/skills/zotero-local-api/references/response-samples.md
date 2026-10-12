# Local API 去敏响应样例

本文记录从真实 Zotero Desktop 的 Local API 采集的响应结构，供解析响应和呈现结果时参考。
归档的上游文档没有给出这些 JSON 形状，示例响应在上游仅以外部 gist 链接存在。
所有题名、作者、标签、集合名、key、用户 ID、时间戳、文件路径、对象版本、结果与子对象数量、附件大小、mtime 和散列值均已替换为虚构值，字段结构和类型与实际响应一致。
采集记录中的 Zotero、API 与 schema 版本用于说明响应来源，不包含用户库内容，因此保留实际值。

采集记录：

- 采集日期：2026-07-20
- Zotero 版本：9.0.6
- `Zotero-API-Version`：3
- `Zotero-Schema-Version`：42
- 采集端点前缀：`http://localhost:23119/api`

## 通用响应特征

- 响应行使用 `HTTP/1.0`，并携带 `X-Zotero-Version` 和 `X-Zotero-Connector-API-Version` header。
- 列表响应携带 `Total-Results` 和 `Link` header。
- `Link` 中 `rel="alternate"` 指向 `https://www.zotero.org/users/<用户 ID>/...`，其中包含真实数字用户 ID，对外展示时应视为隐私数据。
- `GET /api/` 返回 `Content-Type: text/plain`，正文为 `Nothing to see here.`。
- 空列表返回 `[]` 且 `Total-Results: 0`。
- 采集所用的库没有群组和保存的检索，`/users/0/groups` 与 `/users/0/searches` 的响应即为上述空列表形态。
  本地非空对象结构仍未补采，本文后半另行记录了可追溯的 Zotero 官方 Web API v3 公开响应结构。

列表响应 header 示例，取自 `GET /users/0/items/top?limit=2`：

```text
HTTP/1.0 200 OK
X-Zotero-Version: 9.0.6
X-Zotero-Connector-API-Version: 3
Total-Results: 85
Link: <http://localhost:23119/api/users/0/items/top?limit=2&start=84>; rel="last", <http://localhost:23119/api/users/0/items/top?limit=2&start=2>; rel="next", <https://www.zotero.org/users/1234567/items/top>; rel="alternate"
Content-Type: application/json
Zotero-API-Version: 3
Zotero-Schema-Version: 42
```

## 顶层条目

`GET /users/0/items/top?limit=1` 返回条目对象数组，单条读取 `GET /users/0/items/<itemKey>` 返回相同结构的单个对象。
表格摘要列的 creator 来自 `meta.creatorSummary`。
year 只在 `meta.parsedDate` 以四位十进制年份开头时取前四位，否则显示为空，二者在无作者或无日期的条目上可能缺失。

```json
[
  {
    "key": "ABCD2345",
    "version": 120,
    "library": {
      "type": "user",
      "id": 0,
      "name": "Sample User",
      "links": {
        "self": { "href": "http://localhost:23119/api/users/0", "type": "application/json" },
        "alternate": { "href": "https://www.zotero.org/users/1234567", "type": "text/html" }
      }
    },
    "links": {
      "self": { "href": "http://localhost:23119/api/users/0/items/ABCD2345", "type": "application/json" },
      "alternate": { "href": "https://www.zotero.org/users/1234567/items/ABCD2345", "type": "text/html" },
      "attachment": {
        "href": "http://localhost:23119/api/users/0/items/EFGH6789",
        "type": "application/json",
        "attachmentType": "application/pdf",
        "attachmentSize": 123456
      }
    },
    "meta": {
      "creatorSummary": "Doe et al.",
      "parsedDate": "2024-03",
      "numChildren": 1
    },
    "data": {
      "key": "ABCD2345",
      "version": 120,
      "itemType": "journalArticle",
      "title": "Sample Article Title",
      "abstractNote": "Sample abstract text.",
      "date": "2024-03",
      "DOI": "10.0000/sample.doi",
      "url": "https://example.org/sample-article",
      "accessDate": "2026-07-01T00:00:00Z",
      "libraryCatalog": "Example Catalog",
      "extra": "",
      "volume": "12",
      "pages": "34-56",
      "publicationTitle": "Journal of Samples",
      "ISSN": "0000-0000",
      "journalAbbreviation": "J. Samp.",
      "creators": [
        { "firstName": "Jane", "lastName": "Doe", "creatorType": "author" },
        { "firstName": "John", "lastName": "Roe", "creatorType": "author" }
      ],
      "tags": [
        { "tag": "sample-topic", "type": 1 }
      ],
      "collections": ["IJKL2345"],
      "relations": {},
      "dateAdded": "2026-06-01T00:00:00Z",
      "dateModified": "2026-06-02T00:00:00Z"
    }
  }
]
```

`data` 内的字段随 item type 与内容不同而增减，空字段可能整体缺席，客户端必须宽容反序列化。

## 附件子条目

`GET /users/0/items?itemType=attachment&limit=1` 的元素结构如下，也是 `items children` 结果中附件的形态。
与 Web API 不同，`links.enclosure.href` 在 Local API 中直接是本地 `file://` URL，属于隐私数据。
本样例保留虚构的 `file://` URL 以展示结构；向用户转述或写入输出时，应把本地文件路径视为隐私数据。

```json
{
  "key": "EFGH6789",
  "version": 121,
  "library": {
    "type": "user",
    "id": 0,
    "name": "Sample User",
    "links": {
      "self": { "href": "http://localhost:23119/api/users/0", "type": "application/json" },
      "alternate": { "href": "https://www.zotero.org/users/1234567", "type": "text/html" }
    }
  },
  "links": {
    "self": { "href": "http://localhost:23119/api/users/0/items/EFGH6789", "type": "application/json" },
    "alternate": { "href": "https://www.zotero.org/users/1234567/items/EFGH6789", "type": "text/html" },
    "up": { "href": "http://localhost:23119/api/users/0/items/ABCD2345", "type": "application/json" },
    "enclosure": {
      "href": "file:///Users/username/Zotero/storage/EFGH6789/sample.pdf",
      "type": "application/pdf",
      "title": "sample.pdf",
      "length": 123456
    }
  },
  "meta": {
    "numChildren": 0
  },
  "data": {
    "key": "EFGH6789",
    "version": 121,
    "itemType": "attachment",
    "title": "sample.pdf",
    "url": "",
    "accessDate": "",
    "parentItem": "ABCD2345",
    "linkMode": "imported_file",
    "contentType": "application/pdf",
    "charset": "",
    "filename": "sample.pdf",
    "lastRead": 0,
    "mtime": 1750000000000,
    "md5": "0123456789abcdef0123456789abcdef",
    "tags": [],
    "relations": {},
    "dateAdded": "2026-06-01T00:00:00Z",
    "dateModified": "2026-06-02T00:00:00Z"
  }
}
```

## 附件位置

`GET /users/0/items/<itemKey>/file/view/url` 返回单行纯文本，即附件在本机磁盘上的 `file://` URL：

```text
file:///Users/username/Zotero/storage/EFGH6789/sample.pdf
```

## 集合

`GET /users/0/collections?limit=1` 的元素结构如下。
`data.parentCollection` 在顶层集合上为 `false`，在子集合上为父集合的 key 字符串。

```json
[
  {
    "key": "IJKL2345",
    "version": 80,
    "library": {
      "type": "user",
      "id": 0,
      "name": "Sample User",
      "links": {
        "self": { "href": "http://localhost:23119/api/users/0", "type": "application/json" },
        "alternate": { "href": "https://www.zotero.org/users/1234567", "type": "text/html" }
      }
    },
    "links": {
      "self": { "href": "http://localhost:23119/api/users/0/collections/IJKL2345", "type": "application/json" },
      "alternate": { "href": "https://www.zotero.org/users/1234567/collections/IJKL2345", "type": "text/html" }
    },
    "meta": {
      "numCollections": 1,
      "numItems": 12
    },
    "data": {
      "key": "IJKL2345",
      "version": 80,
      "name": "Sample Collection",
      "parentCollection": false,
      "relations": {}
    }
  }
]
```

## 标签

`GET /users/0/tags?limit=1` 的元素结构如下。
标签对象没有 key 与 version，`type` 与 `numItems` 位于 `meta`，`type` 为 `0` 表示用户标签、`1` 表示自动标签。

```json
[
  {
    "tag": "sample-topic",
    "links": {
      "self": { "href": "http://localhost:23119/api/users/0/tags/sample-topic", "type": "application/json" },
      "alternate": { "href": "https://www.zotero.org/users/1234567/tags/sample-topic", "type": "text/html" }
    },
    "meta": {
      "type": 1,
      "numItems": 3
    }
  }
]
```

## 群组

本地采集所用的库没有群组，因此以下非空结构取自 Zotero 官方 Web API 的公开响应。
采集日期为 2026-07-20，请求为 `GET https://api.zotero.org/users/475425/groups?limit=2`，并显式发送 `Zotero-API-Version: 3`。
Local API 文档说明本地群组 metadata 只保留识别群组所需的字段，因此客户端不得要求下列所有可选字段存在。
以下内容已替换群组 ID、用户 ID、名称、描述、时间、版本和数量。

```json
[
  {
    "id": 123456,
    "version": 7,
    "links": {
      "self": { "href": "https://api.zotero.org/groups/123456", "type": "application/json" },
      "alternate": { "href": "https://www.zotero.org/groups/sample_group", "type": "text/html" }
    },
    "meta": {
      "created": "2020-01-01T00:00:00Z",
      "lastModified": "2026-01-01T00:00:00Z",
      "numItems": 7
    },
    "data": {
      "id": 123456,
      "version": 7,
      "name": "Sample Group",
      "owner": 7654321,
      "type": "PublicOpen",
      "description": "<p>Sample group description.</p>",
      "url": "",
      "libraryEditing": "members",
      "libraryReading": "members",
      "fileEditing": "none",
      "members": [7654321, 7654322]
    }
  }
]
```

## 保存的检索

本地采集所用的库没有保存的检索，因此以下非空结构取自 Zotero 官方 Web API 的公开响应。
采集日期为 2026-07-20，请求为 `GET https://api.zotero.org/users/475425/searches?limit=2`，并显式发送 `Zotero-API-Version: 3`。
以下内容已替换检索 key、库信息、名称、条件值和版本。

```json
[
  {
    "key": "MNOP2345",
    "version": 9,
    "library": {
      "type": "user",
      "id": 0,
      "name": "Sample User",
      "links": {
        "alternate": { "href": "https://www.zotero.org/users/1234567", "type": "text/html" }
      }
    },
    "links": {
      "self": {
        "href": "http://localhost:23119/api/users/0/searches/MNOP2345",
        "type": "application/json"
      }
    },
    "data": {
      "key": "MNOP2345",
      "version": 9,
      "name": "Sample Saved Search",
      "conditions": [
        { "condition": "itemType", "operator": "is", "value": "journalArticle" },
        { "condition": "title", "operator": "contains", "value": "sample" }
      ]
    }
  }
]
```
