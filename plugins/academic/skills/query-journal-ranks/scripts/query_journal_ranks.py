#!/usr/bin/env python3
"""Query journal rankings from easyScholar with safe secret handling and rate limiting."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable


API_URL = "https://www.easyscholar.cc/open/getPublicationRank"
MIN_REQUEST_INTERVAL = 0.55
DEFAULT_TIMEOUT = 20.0

FIELD_LABELS = {
    "sciif": "SCI影响因子-JCR",
    "sciif5": "SCI五年影响因子-JCR",
    "sci": "SCI分区-JCR",
    "ssci": "SSCI分区-JCR",
    "jci": "JCI指数-JCR",
    "sciwarn": "中科院预警",
    "sciBase": "SCI基础版分区-中科院",
    "sciUp": "SCI升级版分区-中科院",
    "sciUpSmall": "中科院升级版小类分区",
    "sciUpTop": "中科院升级版Top分区",
    "esi": "ESI学科分类",
    "ccf": "中国计算机学会",
    "zhongguokejihexin": "中国科技核心期刊",
    "fms": "FMS",
    "ajg": "ABS学术期刊指南",
    "utd24": "UTD24",
    "ft50": "FT50",
    "eii": "EI检索",
    "cscd": "中国科学引文数据库",
    "pku": "北大核心",
    "cssci": "南大核心",
    "ahci": "A&HCI",
    "xr": "新锐学术",
    "xrWarn": "新锐学术预警",
    "xrTop": "新锐学术Top分区",
    "xrSmall": "新锐学术小类分区",
    "swufe": "西南财经大学",
    "cufe": "中央财经大学",
    "uibe": "对外经济贸易大学",
    "sdufe": "山东财经大学",
    "xdu": "西安电子科技大学",
    "swjtu": "西南交通大学",
    "ruc": "中国人民大学",
    "xmu": "厦门大学",
    "sjtu": "上海交通大学",
    "fdu": "复旦大学",
    "hhu": "河海大学",
    "cqu": "重庆大学",
    "nju": "南京大学",
    "xju": "新疆大学",
    "cug": "中国地质大学",
    "cju": "长江大学（不是计量大学）",
    "zju": "浙江大学",
    "scu": "四川大学",
    "cpu": "中国药科大学",
}

RANK_TEXT_FIELDS = {
    "1": "oneRankText",
    "2": "twoRankText",
    "3": "threeRankText",
    "4": "fourRankText",
    "5": "fiveRankText",
}


class QueryError(RuntimeError):
    """A sanitized, user-facing query failure."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="查询 easyScholar 期刊等级。")
    parser.add_argument("publication_names", nargs="*", metavar="期刊名")
    parser.add_argument("--stdin", action="store_true", help="从标准输入逐行读取期刊名")
    parser.add_argument(
        "--scope",
        choices=("all", "selected"),
        default="all",
        help="显示全部官方数据集或仅显示用户已选数据集（默认：all）",
    )
    parser.add_argument(
        "--fields",
        help="仅显示这些官方字段，使用逗号分隔，例如 sci,ssci,sciUp,sciif",
    )
    parser.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="输出格式（默认：markdown）",
    )
    parser.add_argument("--no-custom", action="store_true", help="不显示自定义数据集等级")
    parser.add_argument(
        "--secret-key-file",
        type=Path,
        help="从文件首行读取密钥；优先于 EASYSCHOLAR_SECRET_KEY",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help="单次 HTTP 请求超时秒数（默认：20）",
    )
    args = parser.parse_args(argv)

    if not (1 <= args.timeout <= 120):
        parser.error("--timeout 必须在 1 到 120 秒之间")
    if not (args.publication_names or args.stdin):
        parser.error("请提供至少一个期刊名，或使用 --stdin")
    return args


def load_secret(secret_key_file: Path | None) -> str:
    if secret_key_file is not None:
        try:
            secret = secret_key_file.read_text(encoding="utf-8").splitlines()[0].strip()
        except (OSError, IndexError) as exc:
            raise QueryError(f"无法从密钥文件读取首行：{exc}") from None
    else:
        secret = os.environ.get("EASYSCHOLAR_SECRET_KEY", "").strip()
    if not secret:
        raise QueryError(
            "未找到可用密钥；请设置 EASYSCHOLAR_SECRET_KEY 或使用 --secret-key-file。"
        )
    return secret


def deduplicate(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = " ".join(value.split())
        if normalized and normalized.casefold() not in seen:
            seen.add(normalized.casefold())
            result.append(normalized)
    return result


def request_rank(publication_name: str, secret: str, timeout: float) -> dict[str, Any]:
    query = urllib.parse.urlencode(
        {"secretKey": secret, "publicationName": publication_name}
    )
    request = urllib.request.Request(
        f"{API_URL}?{query}",
        headers={"Accept": "application/json", "User-Agent": "query-journal-ranks/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        raise QueryError(f"easyScholar 返回 HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise QueryError(f"easyScholar 请求失败：{reason}") from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise QueryError("easyScholar 返回了无法解析的 JSON") from None
    if not isinstance(payload, dict):
        raise QueryError("easyScholar 返回结构异常：顶层不是对象")
    return payload


def decode_custom_rank(custom_rank: Any) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(custom_rank, dict):
        return [], []
    rank_info = custom_rank.get("rankInfo")
    ranks = custom_rank.get("rank")
    info_by_uuid: dict[str, dict[str, Any]] = {}
    if isinstance(rank_info, list):
        for info in rank_info:
            if isinstance(info, dict) and info.get("uuid") is not None:
                info_by_uuid[str(info["uuid"])] = info

    decoded: list[dict[str, Any]] = []
    warnings: list[str] = []
    if not isinstance(ranks, list):
        return decoded, warnings
    for raw_value in ranks:
        raw = str(raw_value)
        uuid, separator, level = raw.partition("&&&")
        info = info_by_uuid.get(uuid)
        field = RANK_TEXT_FIELDS.get(level)
        rank_text = info.get(field) if info is not None and field else None
        dataset = info.get("abbName") if info is not None else None
        if not separator or info is None or field is None or not rank_text:
            warnings.append(f"无法完整解码自定义等级：{raw}")
        decoded.append(
            {
                "dataset": dataset or uuid or "未知数据集",
                "rank": rank_text or level or raw,
                "level": int(level) if level.isdigit() else level,
                "uuid": uuid or None,
                "raw": raw,
            }
        )
    return decoded, warnings


def normalize_response(
    publication_name: str,
    payload: dict[str, Any],
    scope: str,
    fields: set[str] | None,
    include_custom: bool,
) -> dict[str, Any]:
    code = payload.get("code")
    message = payload.get("msg")
    result: dict[str, Any] = {
        "publicationName": publication_name,
        "code": code,
        "message": message,
        "official": [],
        "custom": [],
        "warnings": [],
    }
    if code != 200 or not isinstance(payload.get("data"), dict):
        return result

    data = payload["data"]
    official = data.get("officialRank")
    official = official if isinstance(official, dict) else {}
    all_ranks = official.get("all") if isinstance(official.get("all"), dict) else {}
    selected_ranks = (
        official.get("select") if isinstance(official.get("select"), dict) else {}
    )
    source = selected_ranks if scope == "selected" else all_ranks
    for field, value in source.items():
        if fields is not None and field not in fields:
            continue
        result["official"].append(
            {
                "field": field,
                "label": FIELD_LABELS.get(field, field),
                "value": value,
                "selected": field in selected_ranks,
            }
        )

    if include_custom:
        custom, warnings = decode_custom_rank(data.get("customRank"))
        result["custom"] = custom
        result["warnings"].extend(warnings)
    return result


def markdown_escape(value: Any) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ")
    for source, replacement in (
        ("\\", "\\\\"),
        ("|", "\\|"),
        ("`", "\\`"),
        ("[", "\\["),
        ("]", "\\]"),
        ("<", "&lt;"),
        (">", "&gt;"),
    ):
        text = text.replace(source, replacement)
    return text


def render_markdown(results: list[dict[str, Any]], scope: str) -> str:
    documents: list[str] = []
    for result in results:
        title = markdown_escape(result["publicationName"])
        lines = [f"## {title}", ""]
        if result.get("error"):
            lines.append(f"- 查询失败：{markdown_escape(result['error'])}")
            documents.append("\n".join(lines))
            continue
        if result.get("code") != 200:
            lines.append(
                f"- 查询失败：code={markdown_escape(result.get('code'))}, "
                f"msg={markdown_escape(result.get('message'))}"
            )
            documents.append("\n".join(lines))
            continue

        official = result.get("official", [])
        custom = result.get("custom", [])
        if official:
            if scope == "all":
                lines.extend(
                    [
                        "| 数据集/指标 | 字段 | 等级或数值 | 已选 |",
                        "|---|---|---|---|",
                    ]
                )
                for row in official:
                    selected = "是" if row["selected"] else ""
                    lines.append(
                        f"| {markdown_escape(row['label'])} | {markdown_escape(row['field'])} | "
                        f"{markdown_escape(row['value'])} | {selected} |"
                    )
            else:
                lines.extend(
                    [
                        "| 数据集/指标 | 字段 | 等级或数值 |",
                        "|---|---|---|",
                    ]
                )
                for row in official:
                    lines.append(
                        f"| {markdown_escape(row['label'])} | {markdown_escape(row['field'])} | "
                        f"{markdown_escape(row['value'])} |"
                    )
        if custom:
            if official:
                lines.append("")
            lines.extend(
                [
                    "| 自定义数据集 | 等级 | 原始编码 |",
                    "|---|---|---|",
                ]
            )
            for row in custom:
                lines.append(
                    f"| {markdown_escape(row['dataset'])} | {markdown_escape(row['rank'])} | "
                    f"{markdown_escape(row['raw'])} |"
                )
        if not official and not custom:
            lines.append("- easyScholar 当前未返回匹配等级。")
        for warning in result.get("warnings", []):
            lines.extend(["", f"- 警告：{markdown_escape(warning)}"])
        documents.append("\n".join(lines))
    return "\n\n".join(documents)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        secret = load_secret(args.secret_key_file)
        names = list(args.publication_names)
        if args.stdin:
            names.extend(line.strip() for line in sys.stdin)
        names = deduplicate(names)
        if not names:
            raise QueryError("没有取得可查询的期刊名")
    except QueryError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    fields = None
    if args.fields:
        fields = {value.strip() for value in args.fields.split(",") if value.strip()}
        if not fields:
            print("错误：--fields 没有包含有效字段", file=sys.stderr)
            return 2

    results: list[dict[str, Any]] = []
    last_started: float | None = None
    had_error = False
    for publication_name in names:
        if last_started is not None:
            remaining = MIN_REQUEST_INTERVAL - (time.monotonic() - last_started)
            if remaining > 0:
                time.sleep(remaining)
        last_started = time.monotonic()
        try:
            payload = request_rank(publication_name, secret, args.timeout)
            result = normalize_response(
                publication_name,
                payload,
                args.scope,
                fields,
                not args.no_custom,
            )
            if result.get("code") != 200:
                had_error = True
        except QueryError as exc:
            result = {
                "publicationName": publication_name,
                "error": str(exc),
                "official": [],
                "custom": [],
                "warnings": [],
            }
            had_error = True
        results.append(result)

    if args.format == "json":
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(results, args.scope))
    return 1 if had_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
