# Zotero Local API 中文参考

本文完整翻译自 Zotero 官方文档 [Local API](https://www.zotero.org/support/dev/web_api/v3/local_api) 页面，归档版本和页面更新时间见[参考资料索引](README.md)。
若译文与官方原文或实际行为不一致，以官方原文和实际测试结果为准。

较新版本的 Zotero 桌面客户端在 `localhost:23119` 的 `/api/` 路径下提供 [Zotero Web API](read-requests.md) 的本地实现，从用户的本地数据库提供数据。
Local API 不访问网络，因此可以离线工作，没有速率限制，并且通常比 Web API 快得多。
它面向在用户本人计算机上运行的工具和命令行程序，使这些程序不必直接读取 SQLite 数据库，也不必退回 Web API。

必须在 Zotero 的设置中启用 Local API，路径为 Settings → Advanced → “Allow other applications on this computer to communicate with Zotero”。
未启用时，请求返回 `403 Forbidden`。

基础 URL 为：

```text
http://localhost:23119/api/
```

[读取接口中文摘译](read-requests.md)中记录的大多数端点加上此前缀后都以相同方式工作。
Local API 与 Web API 的主要差异如下：

- Local API 只支持 API version 3，并且任何时候都只支持一个版本。
  如果将来发布新版本，而客户端需要同时兼容新旧 Zotero，应先请求 `/api/`，读取响应头 `Zotero-API-Version`，确定正在运行的客户端所使用的版本，再发送其他请求。
- 当前不支持写请求，只接受 `GET`。
  Zotero 的后续版本将支持写请求。
- Local API 不进行身份验证。
  任何能够访问 loopback 接口的程序都能读取用户的文献库，因此不得转发该端口或以其他方式将它暴露到外部。
- 只能访问本地已登录用户的数据。
  用户 ID 可以传 `0`，也可以传用户的实际数字 ID；后者可在 [API Keys](https://www.zotero.org/settings/keys) 页面查看。
  请求其他用户 ID 会返回 `400`。
- 群组元数据仅包含识别群组所需的信息，不包含权限、成员列表等详情。
- 不支持 Atom。
  使用 `format=atom` 或 `content=atom` 的请求返回 `501 Not Implemented`。
- 条目类型和字段端点的说明见[条目类型与字段中文摘译](types-and-fields.md)。
  这些端点根据用户的 locale 返回本地化名称，并忽略 `locale` 查询参数。
  `/api/creatorFields` 是例外，它与 Web API 一样始终返回英文名称。
- 默认不对结果分页。
  Local API 会在一个响应中返回全部匹配对象；需要分页时仍可使用 `limit` 和 `start`，响应也仍包含 `Link` header。
- 实现目标是匹配 Web API 的文档行为，但不会复现其每个实现细节。
  相同排序键下的顺序、quicksearch 的匹配方式以及对象 JSON 的精确内容可能有细微差异。
  依赖 Web API 未定义行为或少见边界情况的客户端，应同时针对两种实现进行测试。

Local API 还支持下列 Web API 不提供的能力：

- `<userOrGroupPrefix>/searches/<searchKey>/items` 返回与指定保存的检索相匹配的条目。
  Web API 仅提供检索元数据，不执行检索。
- `<userOrGroupPrefix>/items/<itemKey>/file` 返回 `302` 重定向，目标是磁盘上附件的 `file://` URL，`/file/view` 的行为相同。
  `/file/view/url` 不进行重定向，而是以纯文本返回该 URL。

响应包含 `Zotero-Schema-Version` header，表示本地 Zotero 实例的 schema version。
该版本可能落后于 Web API 所使用的版本，也可能领先于它。

API 的资源、读取参数、检索、排序和缓存规则见[读取接口中文摘译](read-requests.md)。
