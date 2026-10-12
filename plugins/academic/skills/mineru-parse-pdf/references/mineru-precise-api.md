# MinerU 精准解析 API 参考

来源：[MinerU 文档解析接口文档](https://mineru.net/apiManage/docs)
核对日期：2026 年 8 月 11 日。

## 接口与限制

精准解析 API 请求头必须包含 `Authorization: Bearer <token>`。

本技能只处理 PDF，并采用以下限制：

- 单文件不超过 200 MB
- 单文件不超过 200 页
- 本地文件申请上传链接时每批不超过 50 个
- PDF URL 批量提交时每批不超过 50 个
- 本地上传链接有效期为 24 小时
- 上传文件时不设置 `Content-Type`

官方概览中的批量能力汇总值与详细接口说明存在差异。
执行时采用详细接口明确给出的 50 个文件上限。

## 本地 PDF 流程

向 `POST https://mineru.net/api/v4/file-urls/batch` 提交请求：

```json
{
  "files": [
    {
      "name": "demo.pdf",
      "data_id": "pdf-0-example"
    }
  ],
  "model_version": "vlm",
  "enable_formula": true,
  "enable_table": true,
  "language": "en"
}
```

响应中的 `data.batch_id` 用于轮询，`data.file_urls` 按请求文件顺序提供上传地址。
对每个地址执行 `PUT` 上传后，无需再次提交任务。

仅在外部 PDF 探查确认后，才在对应的 `files` 条目中加入 `"is_ocr": true`。
页码范围同样放在文件条目中，例如 `"page_ranges": "2,4-6"`。

## PDF URL 流程

向 `POST https://mineru.net/api/v4/extract/task/batch` 提交请求：

```json
{
  "files": [
    {
      "url": "https://example.com/paper.pdf",
      "data_id": "pdf-0-example"
    }
  ],
  "model_version": "vlm",
  "enable_formula": true,
  "enable_table": true,
  "language": "en"
}
```

`no_cache` 和 `cache_tolerance` 只用于 URL 任务。
本技能不传 `extra_formats`，因为 Markdown 和 JSON 已由服务默认生成，而交付阶段只保留 Markdown 与其插图。

## 轮询与结果

使用 `GET https://mineru.net/api/v4/extract-results/batch/{batch_id}` 轮询批次。

活动状态包括：

- `waiting-file`
- `pending`
- `running`
- `converting`

终止状态包括：

- `done`
- `failed`

完成条目通过 `full_zip_url` 提供 MinerU 原始结果包。
原始包中的 `full.md` 是 Markdown 结果，插图通常位于 `images/`，其余文件用于结构化处理和调试。
本技能在临时目录解压原始包，把 Markdown 图片引用改写到 `figs/`，然后只打包 Markdown 和被引用的图片。

官方文档示例使用 `code`、`msg` 和 `data` 响应字段。
2026 年 8 月 11 日的真实鉴权失败响应使用 `success`、`msgCode`、`msg` 和 `data` 字段。
脚本必须兼容两种响应外壳，并且不得在错误信息中回显 Token 或签名 URL 参数。

## 参数与错误处理

`model_version` 对 PDF 可使用 `pipeline` 或 `vlm`，本技能默认使用 `vlm`。
`enable_formula` 和 `enable_table` 默认启用。
`is_ocr` 默认关闭，且只在外部探查后启用。

常用语言代码包括：

- `ch` 用于简体中文、英文和繁体中文混排
- `en` 用于纯英文
- `ch_server` 用于繁体中文和手写体场景
- `chinese_cht` 用于繁体中文为主的文档
- `japan` 用于日文为主的文档
- `korean` 用于韩文
- `latin` 用于法语、德语、西班牙语等拉丁语系语言
- `arabic` 用于阿拉伯语系语言
- `cyrillic` 用于俄语等西里尔语系语言
- `east_slavic` 用于东斯拉夫语系语言
- `devanagari` 用于印地语等天城文语系语言

常见错误码包括：

- `A0202` 表示 Token 错误或鉴权失败
- `A0211` 表示 Token 过期
- `-500` 表示传参错误
- `-10001` 表示服务异常
- `-10002` 表示请求参数错误
- `-60001` 表示生成上传 URL 失败
- `-60002` 表示无法识别文件格式
- `-60003` 表示文件读取失败
- `-60004` 表示空文件
- `-60005` 表示文件大小超限
- `-60006` 表示文件页数超限
- `-60007` 表示模型服务暂时不可用
- `-60008` 表示文件读取超时
- `-60009` 表示任务队列已满
- `-60010` 表示解析失败
- `-60011` 表示没有获取到有效上传文件
- `-60012` 表示找不到任务
- `-60013` 表示无权访问任务
- `-60015` 和 `-60016` 表示文件转换失败
- `-60018` 表示当日任务数量已达上限

对临时服务异常和队列已满错误可稍后重试。
对鉴权、参数、文件限制和权限错误应先修正原因，不要无条件重试。
