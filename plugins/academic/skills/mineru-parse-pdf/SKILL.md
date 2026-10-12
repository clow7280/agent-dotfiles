---
name: mineru-parse-pdf
description: 使用 MinerU 精准解析 API 将本地 PDF、PDF 文件夹或 PDF URL 解析为 Markdown，并将 Markdown 与可选插图整理为 ZIP 交付包。适用于论文、报告等 PDF 的 Markdown 转换、OCR 解析、批量解析和解析质量检查；不用于导出 DOCX、HTML、LaTeX、JSON 或其他格式。
---

# MinerU PDF 转 Markdown

## 目标与边界

只把 PDF 解析为 Markdown 文档。
最终为每个 PDF 交付一个 ZIP 文件，其中包含一个 Markdown 文件和可选的 `figs/` 插图目录。
不得把 MinerU 原始 ZIP、JSON、调试文件或其他导出格式放入交付包。

使用 MinerU 精准解析 API，默认选择 `vlm` 模型。
精准 API 支持单文件不超过 200 MB、200 页，本地文件和 URL 批次均不超过 50 个 PDF。

只从 `MINERU_API_KEY` 或 `MINERU_TOKEN` 环境变量读取 Token。
不得把 Token 写入技能文件、项目文件、命令参数、日志或交付包。

## 解析前探查

必须在调用 MinerU 前从脚本外部探查 PDF，不得让解析脚本自行猜测是否需要 OCR。

对本地 PDF 执行以下探查：

1. 使用 `pdfinfo` 检查文件类型、页数和基本元数据
2. 使用 `pdffonts` 检查是否存在可用字体和文本层
3. 使用 `pdftotext` 抽取首页、摘要页及若干正文页的样本文本
4. 必要时渲染代表性页面，目视检查扫描图像、乱码、错栏和文字缺失

上述工具来自 poppler；缺失时先请用户安装，再执行探查。

对 PDF URL，先把探查副本下载到系统临时目录，再执行相同检查。
完成探查后删除临时副本，不在项目根目录散落文件。

仅在样本文本为空、明显过少、严重乱码或页面主要由扫描图像构成时启用 `--ocr`。
存在质量正常的文本层时不要启用 OCR。

从标题、摘要和正文样本推测主要语言。
纯英文优先使用 `en`，中英文混排优先使用 `ch`，其他语言按 [API 参考](references/mineru-precise-api.md) 选择语言包。
启用 `--ocr` 时必须显式传入 `--language`。

## 解析流程

使用 `uv` 在本技能目录下运行脚本；在其他目录执行时改用脚本的绝对路径。
先在当前终端安全设置 Token 环境变量，再执行解析命令。

解析本地 PDF：

```bash
uv run scripts/mineru_parse.py papers/example.pdf --out parsed --language en
```

解析目录内全部 PDF：

```bash
uv run scripts/mineru_parse.py papers --out parsed --language ch
```

解析 PDF URL：

```bash
uv run scripts/mineru_parse.py --url https://example.com/paper.pdf --out parsed --language en
```

仅在外部探查确认需要 OCR 后执行：

```bash
uv run scripts/mineru_parse.py scans/example.pdf --out parsed --ocr --language ch
```

默认保留公式和表格识别。
只有用户明确不需要时才使用 `--no-formula` 或 `--no-table`。
不要请求 `docx`、`html`、`latex` 或其他额外格式。

修改脚本、排查接口字段或处理错误码时，读取 [API 参考](references/mineru-precise-api.md)。

## ZIP 交付契约

脚本默认在 `parsed/` 中为每个 PDF 创建一个 ZIP 文件：

```text
parsed/<pdf-stem>.zip
```

ZIP 内部结构固定为：

```text
<pdf-stem>.md
figs/
```

`figs/` 仅在 Markdown 包含本地插图时存在。
Markdown 内的本地图片引用必须统一指向 `figs/`，且每个引用都必须能在 ZIP 中找到对应文件。
ZIP 中不得出现 Markdown 和 `figs/` 之外的文件。

## 质量验收

对每个 ZIP 运行质量探查脚本：

```bash
uv run scripts/markdown_quality.py parsed/example.zip --json
```

验收时确认：

- `effective_line_count` 和 `character_count` 与 PDF 篇幅大致匹配
- `missing_image_refs` 为空
- `unexpected_files` 为空
- 标题、摘要、章节顺序、表格、公式和图注与原 PDF 大致一致
- Markdown 的主要语言与解析前推测一致

若有效行数或字符数异常偏低，重新检查文本层、OCR 决策、语言参数和页码范围。
若主要语言难以从统计值判断，由 Agent 阅读标题、摘要和正文样本后推测，不在质量脚本中自动判定。
重要论断以及可疑的表格、公式和图文关系必须回查原 PDF。

## 维护

修改脚本后运行测试：

```bash
uv run --with pytest --with requests python -m pytest tests/
```
