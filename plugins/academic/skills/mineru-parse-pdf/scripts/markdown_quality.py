#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# ///
"""统计 MinerU Markdown 交付物的基础质量指标。"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]\n]*\]\((?P<target><[^>\n]+>|[^\s)]+)[^)\n]*\)")
HTML_IMAGE_RE = re.compile(
    r"<img\b[^>]*?\bsrc\s*=\s*['\"](?P<target>.*?)['\"]", re.IGNORECASE
)


class QualityError(RuntimeError):
    """表示交付物无法检查或不符合结构约定。"""


def image_targets(markdown: str) -> list[str]:
    targets = [match.group("target") for match in MARKDOWN_IMAGE_RE.finditer(markdown)]
    targets.extend(match.group("target") for match in HTML_IMAGE_RE.finditer(markdown))
    return targets


def local_image_path(raw_target: str) -> str | None:
    angled = raw_target.startswith("<") and raw_target.endswith(">")
    target = raw_target[1:-1] if angled else raw_target
    parsed = urllib.parse.urlsplit(target)
    if parsed.scheme or parsed.netloc or target.startswith("data:"):
        return None
    normalized = PurePosixPath(urllib.parse.unquote(parsed.path)).as_posix()
    return normalized


def text_metrics(markdown: str) -> dict[str, int]:
    lines = markdown.splitlines()
    return {
        "line_count": len(lines),
        "effective_line_count": sum(1 for line in lines if line.strip()),
        "character_count": len(markdown.replace("\r", "").replace("\n", "")),
        "non_whitespace_character_count": sum(1 for char in markdown if not char.isspace()),
    }


def inspect_markdown(path: Path) -> dict[str, Any]:
    markdown = path.read_text(encoding="utf-8", errors="strict")
    missing: list[str] = []
    local_targets: list[str] = []
    for target in image_targets(markdown):
        local = local_image_path(target)
        if local is None:
            continue
        local_targets.append(local)
        if not (path.parent / local).is_file():
            missing.append(local)
    return {
        "source": str(path),
        **text_metrics(markdown),
        "local_image_count": len(set(local_targets)),
        "missing_image_refs": sorted(set(missing)),
    }


def inspect_zip(path: Path) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(path) as archive:
            files = {name for name in archive.namelist() if not name.endswith("/")}
            markdown_files = sorted(
                name
                for name in files
                if PurePosixPath(name).parent == PurePosixPath(".")
                and name.lower().endswith(".md")
            )
            if len(markdown_files) != 1:
                raise QualityError("ZIP 根目录必须恰好包含一个 Markdown 文件。")
            markdown_name = markdown_files[0]
            markdown = archive.read(markdown_name).decode("utf-8", errors="strict")
    except zipfile.BadZipFile as exc:
        raise QualityError("输入不是有效 ZIP 文件。") from exc

    unexpected = sorted(
        name
        for name in files
        if name != markdown_name and not name.startswith("figs/")
    )
    local_targets = [
        local
        for target in image_targets(markdown)
        if (local := local_image_path(target)) is not None
    ]
    missing = sorted({target for target in local_targets if target not in files})
    return {
        "source": str(path),
        "markdown_file": markdown_name,
        **text_metrics(markdown),
        "local_image_count": len(set(local_targets)),
        "missing_image_refs": missing,
        "unexpected_files": unexpected,
    }


def inspect(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise QualityError(f"输入文件不存在: {path}")
    if path.suffix.lower() == ".md":
        return inspect_markdown(path)
    if path.suffix.lower() == ".zip":
        return inspect_zip(path)
    raise QualityError("仅支持 .md 或 .zip 文件。")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="统计 Markdown 有效行数、字符数和图片完整性。")
    parser.add_argument("input", help="Markdown 文件或 MinerU 交付 ZIP。")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出检查结果。")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    result = inspect(Path(args.input).expanduser().resolve())
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"有效行数: {result['effective_line_count']}")
        print(f"字符数: {result['character_count']}")
        print(f"非空白字符数: {result['non_whitespace_character_count']}")
        print(f"本地图片数: {result['local_image_count']}")
        print(f"缺失图片引用数: {len(result['missing_image_refs'])}")
        if "unexpected_files" in result:
            print(f"非预期文件数: {len(result['unexpected_files'])}")
    has_problem = bool(result["missing_image_refs"] or result.get("unexpected_files"))
    return 1 if has_problem else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except (OSError, UnicodeError, QualityError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        raise SystemExit(1)
