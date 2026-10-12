#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "requests>=2.31,<3",
# ]
# ///
"""Search WOSCC and return quick JSON or full-field TSV plus normalized JSONL."""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
import tempfile
import time
from datetime import date
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit


MAX_QUICK = 20
MAX_DEFAULT = 200
MAX_JSON = 100
MAX_NORMAL = 1000
MAX_LARGE = 100000

EDITION_ALIASES = {
    "SCI": "SCI-EXPANDED",
    "SCIE": "SCI-EXPANDED",
    "SCI-E": "SCI-EXPANDED",
    "SCIEXPANDED": "SCI-EXPANDED",
    "SCI-EXPANDED": "SCI-EXPANDED",
    "ESCI": "ESCI",
    "SSCI": "SSCI",
    "AHCI": "A&HCI",
    "A&HCI": "A&HCI",
    "CPCI-S": "CPCI-S",
    "CPCI-SSH": "CPCI-SSH",
    "BKCI-S": "BKCI-S",
    "BKCI-SSH": "BKCI-SSH",
}


class JsonArgumentParser(argparse.ArgumentParser):
    """Emit machine-readable argument errors for agent callers."""

    def error(self, message: str) -> None:
        print(
            json.dumps(
                {"ok": False, "stage": "arguments", "code": "invalid_arguments", "error": message},
                ensure_ascii=False,
            )
        )
        raise SystemExit(2)


class SkillError(RuntimeError):
    def __init__(self, stage: str, code: str, message: str):
        super().__init__(message)
        self.stage = stage
        self.code = code


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def sanitize_error(value: object) -> str:
    text = str(value)
    def strip_url_query(match: re.Match[str]) -> str:
        raw = match.group(0)
        trailing = ""
        while raw and raw[-1] in ").,;]":
            trailing = raw[-1] + trailing
            raw = raw[:-1]
        try:
            parts = urlsplit(raw)
            clean = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
        except ValueError:
            clean = "<redacted-url>"
        return clean + trailing

    text = re.sub(r"https?://[^\s<>\"']+", strip_url_query, text, flags=re.IGNORECASE)
    text = re.sub(
        r"(x-1p-wos-sid[^A-Za-z0-9]+)[A-Za-z0-9]+",
        r"\1<redacted>",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\b(sid|auth(?:orization|code)?|samlresponse|relaystate|token|cookie|session)="
        r"[^&\s'\"]+",
        r"\1=<redacted>",
        text,
        flags=re.IGNORECASE,
    )
    return text[:1000]


def positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("必须是整数") from exc
    if number < 1:
        raise argparse.ArgumentTypeError("必须是正整数")
    return number


def option_provided(name: str) -> bool:
    """判断命令行是否显式提供了某个选项（用于拒绝对当前模式无意义的组合）。"""
    return any(item == name or item.startswith(name + "=") for item in sys.argv[1:])


def validate_prefix(value: str) -> str:
    if (
        not re.fullmatch(r"[\w.-]{1,80}", value, flags=re.UNICODE)
        or value.startswith(".")
        or ".." in value
    ):
        raise argparse.ArgumentTypeError("仅允许 1–80 个字母、数字、下划线、点或连字符，且不得含路径片段")
    return value


def normalize_editions(raw: str | None) -> list[str]:
    if raw is None:
        return []
    requested: list[str] = []
    unknown: list[str] = []
    for item in raw.split(","):
        key = item.strip().upper()
        if not key:
            continue
        canonical = EDITION_ALIASES.get(key)
        if canonical is None:
            unknown.append(item.strip())
        elif canonical not in requested:
            requested.append(canonical)
    if unknown:
        allowed = ", ".join(sorted(set(EDITION_ALIASES)))
        raise argparse.ArgumentTypeError(
            "未知 citation index: %s；允许值: %s" % (", ".join(unknown), allowed)
        )
    if not requested:
        raise argparse.ArgumentTypeError("citation index 不能为空")
    return requested


def parse_args() -> argparse.Namespace:
    parser = JsonArgumentParser(
        description="WOSCC 检索：快速 JSON 或 TSV-first 全字段获取",
        allow_abbrev=False,
    )
    parser.add_argument("--query", help="WoS 高级检索式")
    parser.add_argument("--check-access", action="store_true", help="只探查机构网络访问权限")
    parser.add_argument("--count-only", action="store_true", help="只返回 WOSCC 预过滤命中数")
    parser.add_argument("--format", choices=["tsv", "json"], default="tsv", help="默认 tsv")
    parser.add_argument(
        "--max",
        type=positive_int,
        default=None,
        help="取回上限；JSON 默认 20，TSV 默认 200",
    )
    parser.add_argument("--allow-large", action="store_true", help="允许 1001–100000 条批量任务")
    parser.add_argument("--sort", choices=["relevance", "date"], default="relevance")
    parser.add_argument(
        "--content",
        choices=["authorsTitleSource", "authorsTitleSourceAbstract", "fullRecord", "fullRecordPlus"],
        default="fullRecord",
        help="TSV 字段范围；CR 需要 fullRecordPlus",
    )
    parser.add_argument("--editions", help="逗号分隔，如 SCIE,ESCI；仅支持 TSV 后过滤")
    parser.add_argument(
        "--allow-truncated-edition",
        action="store_true",
        help="显式接受只在 WOSCC 排序前 N 条中做 edition 后过滤",
    )
    parser.add_argument(
        "--outdir",
        help="TSV/JSONL 新目录（必须尚不存在，父目录可存在）；建议放在会话临时目录",
    )
    parser.add_argument("--prefix", type=validate_prefix, default="wos", help="安全输出文件名前缀")
    args = parser.parse_args()

    try:
        args.editions = normalize_editions(args.editions)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))

    if args.max is None:
        args.max = MAX_QUICK if args.format == "json" else MAX_DEFAULT

    if not args.check_access and not args.query:
        parser.error("--query 必填，除非使用 --check-access")
    if args.check_access and args.query:
        parser.error("--check-access 不得与 --query 同时使用")
    if args.check_access and args.count_only:
        parser.error("--check-access 不得与 --count-only 同时使用")
    if args.check_access:
        if len(sys.argv) != 2:
            parser.error("--check-access 必须单独使用，不接受其他参数")
        return args
    if not args.count_only and args.format == "json" and args.editions:
        parser.error("JSON 记录不含 WE，citation index 限定必须使用 --format tsv")
    if args.allow_truncated_edition and not args.editions:
        parser.error("--allow-truncated-edition 只能与 --editions 联用")
    if args.count_only and args.allow_truncated_edition:
        parser.error("count-only 未执行 edition 后过滤，不能使用 --allow-truncated-edition")
    if args.count_only:
        for option in ("--format", "--content", "--outdir", "--prefix", "--allow-large"):
            if option_provided(option):
                parser.error("--count-only 只返回命中数，不得使用 %s" % option)
    if not args.count_only and args.format == "json":
        for option in ("--content", "--outdir", "--prefix", "--allow-large"):
            if option_provided(option):
                parser.error("%s 只适用于 --format tsv" % option)
    if not args.count_only and args.format == "json" and args.max > MAX_JSON:
        parser.error("JSON 快速路径最多取回 %d 条" % MAX_JSON)
    if not args.count_only and args.max > MAX_LARGE:
        parser.error("--max 不得超过 %d" % MAX_LARGE)
    if not args.count_only and args.max > MAX_NORMAL and not args.allow_large:
        parser.error("超过 %d 条必须在用户确认后显式添加 --allow-large" % MAX_NORMAL)
    if (
        not args.check_access
        and not args.count_only
        and args.format == "tsv"
        and not args.outdir
    ):
        parser.error("TSV 模式需要 --outdir")
    return args


def load_backend():
    """加载技能自带的 WoS 接口后端（scripts/wos_backend.py，与本脚本同目录）。"""
    try:
        from wos_backend import EXPORT_BATCH, bootstrap, fetch_records_json, run_query
    except (ImportError, AttributeError) as exc:
        raise SkillError(
            "dependencies",
            "backend_incompatible",
            "无法加载内置后端 scripts/wos_backend.py（技能文件不完整或被改动）: %s"
            % sanitize_error(exc),
        ) from exc
    return EXPORT_BATCH, bootstrap, fetch_records_json, run_query


def edition_codes(value: str) -> set[str]:
    upper = (value or "").upper()
    codes = {match.strip().upper() for match in re.findall(r"\(([^()]+)\)", upper)}
    return {EDITION_ALIASES.get(code, code) for code in codes}


def read_validated_tsv(
    path: Path, expected_rows: int | None = None
) -> tuple[list[str], list[dict[str, str]]]:
    """Read one export batch and fail closed on structural or identity errors."""
    required = {"UT", "TI", "WE"}
    rows: list[dict[str, str]] = []
    seen_ut: set[str] = set()
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as source:
            reader = csv.reader(source, delimiter="\t")
            try:
                header = next(reader)
            except StopIteration as exc:
                raise SkillError("validate_tsv", "empty_tsv", "%s 是空文件" % path) from exc
            if not header or any(not field for field in header):
                raise SkillError("validate_tsv", "invalid_header", "%s 表头包含空字段" % path)
            duplicates = sorted({field for field in header if header.count(field) > 1})
            if duplicates:
                raise SkillError(
                    "validate_tsv",
                    "duplicate_columns",
                    "%s 表头重复: %s" % (path, ",".join(duplicates)),
                )
            missing = sorted(required - set(header))
            if missing:
                raise SkillError(
                    "validate_tsv", "missing_columns", "%s 缺少列: %s" % (path, ",".join(missing))
                )
            for values in reader:
                if len(values) != len(header):
                    raise SkillError(
                        "validate_tsv",
                        "column_count_mismatch",
                        "%s 第 %d 个物理行有 %d 列，表头为 %d 列"
                        % (path, reader.line_num, len(values), len(header)),
                    )
                row = dict(zip(header, values))
                ut = row["UT"].strip()
                if not ut:
                    raise SkillError(
                        "validate_tsv", "missing_ut", "%s 第 %d 个物理行缺少 UT" % (path, reader.line_num)
                    )
                if not row["TI"].strip():
                    raise SkillError(
                        "validate_tsv", "missing_title", "%s 第 %d 个物理行缺少 TI" % (path, reader.line_num)
                    )
                if not row["WE"].strip():
                    raise SkillError(
                        "validate_tsv", "missing_we_value", "%s 第 %d 个物理行缺少 WE" % (path, reader.line_num)
                    )
                if ut in seen_ut:
                    raise SkillError(
                        "validate_tsv", "duplicate_ut", "%s 出现重复 UT: %s" % (path, ut)
                    )
                seen_ut.add(ut)
                rows.append(row)
    except UnicodeDecodeError as exc:
        raise SkillError("validate_tsv", "invalid_encoding", "%s 不是有效 UTF-8 TSV" % path) from exc
    if expected_rows is not None and len(rows) != expected_rows:
        raise SkillError(
            "validate_tsv",
            "record_count_mismatch",
            "%s 期望 %d 条，实际 %d 条" % (path, expected_rows, len(rows)),
        )
    return header, rows


def export_tsv(
    session,
    sid: str,
    origin: str,
    qid: str,
    mark_from: int,
    mark_to: int,
    content: str,
    path: Path,
    sort: str,
    expected_rows: int,
) -> int:
    if path.exists() or path.with_suffix(path.suffix + ".part").exists():
        raise SkillError("export", "output_exists", "输出已存在: %s" % path)
    body = {
        "parentQid": qid,
        "sortBy": sort,
        "displayTimesCited": "true",
        "displayCitedRefs": "true",
        "displayUsageInfo": "true",
        "product": "UA",
        "colName": "WOS",
        "fileOpt": "othersoftware",
        "action": "saveToTab",
        "markFrom": str(mark_from),
        "markTo": str(mark_to),
        "view": "summary",
        "isRefQuery": "false",
        "locale": "en_US",
        "filters": content,
    }
    response = session.post(
        origin + "/api/wosnx/indic/export/saveToFile",
        data=json.dumps(body),
        headers={
            "accept": "application/json, text/plain, */*",
            "content-type": "application/json",
            "x-1p-wos-sid": sid,
            "origin": origin,
            "referer": origin + "/wos/woscc/summary/%s/%s/1" % (qid, sort),
        },
        timeout=180,
    )
    response.raise_for_status()
    content_type = response.headers.get("content-type", "").lower()
    if "text/plain" not in content_type:
        raise SkillError(
            "export",
            "unexpected_content_type",
            "导出未返回 TSV，content-type=%s" % content_type,
        )
    part = path.with_suffix(path.suffix + ".part")
    try:
        with part.open("xb") as handle:
            handle.write(response.content)
        read_validated_tsv(part, expected_rows=expected_rows)
        part.replace(path)
    except Exception:
        part.unlink(missing_ok=True)
        raise
    return len(response.content)


def filter_tsv(path: Path, wanted: set[str]) -> tuple[int, int]:
    """Filter a TSV in place by the WE field. Return (kept, total)."""
    header, rows = read_validated_tsv(path)
    temporary: Path | None = None
    kept = 0
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=".%s." % path.name,
            suffix=".filtering",
            delete=False,
        ) as destination:
            temporary = Path(destination.name)
            writer = csv.DictWriter(
                destination,
                fieldnames=header,
                delimiter="\t",
                lineterminator="\r\n",
                extrasaction="raise",
            )
            writer.writeheader()
            for row in rows:
                if edition_codes(row["WE"]) & wanted:
                    writer.writerow(row)
                    kept += 1
        read_validated_tsv(temporary, expected_rows=kept)
        temporary.replace(path)
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise
    return kept, len(rows)


def split_semicolon(value: str | None) -> list[str]:
    return [item.strip() for item in (value or "").split(";") if item.strip()]


def int_or_none(value: str | None) -> int | None:
    try:
        return int((value or "").strip())
    except (TypeError, ValueError):
        return None


def normalized_record(row: dict[str, str | None], rank: int) -> dict[str, Any]:
    return {
        "rank": rank,
        "ut": (row.get("UT") or "").strip() or None,
        "doi": (row.get("DI") or "").strip() or None,
        "title": (row.get("TI") or "").strip() or None,
        "authors": split_semicolon(row.get("AU")),
        "source": (row.get("SO") or "").strip() or None,
        "year": int_or_none(row.get("PY")),
        "doc_type": split_semicolon(row.get("DT")),
        "volume": (row.get("VL") or "").strip() or None,
        "issue": (row.get("IS") or "").strip() or None,
        "start_page": (row.get("BP") or "").strip() or None,
        "end_page": (row.get("EP") or "").strip() or None,
        "article_number": (row.get("AR") or "").strip() or None,
        "author_keywords": split_semicolon(row.get("DE")),
        "keywords_plus": split_semicolon(row.get("ID")),
        "abstract": (row.get("AB") or "").strip() or None,
        "times_cited_woscc": int_or_none(row.get("TC")),
        "times_cited_all": int_or_none(row.get("Z9")),
        "cited_references": split_semicolon(row.get("CR")),
        "wos_index": (row.get("WE") or "").strip() or None,
        "wos_index_codes": sorted(edition_codes(row.get("WE", ""))),
    }


def normalize_tsv(paths: Iterable[Path], output: Path) -> int:
    if output.exists() or output.with_suffix(output.suffix + ".part").exists():
        raise SkillError("normalize", "output_exists", "输出已存在: %s" % output)
    part = output.with_suffix(output.suffix + ".part")
    count = 0
    seen_ut: set[str] = set()
    try:
        with part.open("x", encoding="utf-8", newline="\n") as destination:
            for path in paths:
                _header, rows = read_validated_tsv(path)
                for row in rows:
                    count += 1
                    record = normalized_record(row, count)
                    ut = record["ut"]
                    if ut in seen_ut:
                        raise SkillError("normalize", "duplicate_ut", "发现重复 UT: %s" % ut)
                    seen_ut.add(ut)
                    destination.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        part.replace(output)
    except Exception:
        part.unlink(missing_ok=True)
        raise
    return count


def validate_json_records(records: list[dict[str, Any]], target: int) -> None:
    required = {
        "pos",
        "ut",
        "doi",
        "title",
        "source",
        "authors",
        "pubyear",
        "doctypes",
        "times_cited",
        "abstract",
    }
    if len(records) != target:
        raise SkillError(
            "json_fetch",
            "record_count_mismatch",
            "期望 %d 条，实际 %d 条" % (target, len(records)),
        )
    if any(not isinstance(record, dict) for record in records):
        raise SkillError("json_fetch", "invalid_record_type", "JSON 记录必须是对象")
    positions = [record.get("pos") for record in records]
    if any(type(position) is not int for position in positions):
        raise SkillError("json_fetch", "invalid_position_type", "JSON pos 必须是整数")
    if positions != list(range(1, target + 1)):
        raise SkillError("json_fetch", "position_gap", "JSON 记录位置不连续")
    seen_ut: set[str] = set()
    for record in records:
        missing = required - set(record)
        if missing:
            raise SkillError("json_fetch", "missing_fields", "JSON 缺少字段: %s" % ",".join(sorted(missing)))
        for field in ("ut", "title", "source"):
            value = record.get(field)
            if not isinstance(value, str) or not value.strip():
                raise SkillError("json_fetch", "missing_identity", "JSON %s 必须是非空字符串" % field)
        for field in ("authors", "doctypes"):
            value = record.get(field)
            if not isinstance(value, list) or any(
                not isinstance(item, str) or not item.strip() for item in value
            ):
                raise SkillError("json_fetch", "invalid_list_field", "JSON %s 必须是字符串数组" % field)
        for field in ("doi",):
            value = record.get(field)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise SkillError("json_fetch", "invalid_optional_string", "JSON %s 类型无效" % field)
        abstract = record.get("abstract")
        if abstract is not None and not isinstance(abstract, str):
            raise SkillError("json_fetch", "invalid_abstract", "JSON abstract 必须是字符串或 null")
        for field in ("pubyear", "times_cited"):
            value = record.get(field)
            if isinstance(value, str) and re.fullmatch(r"\d+", value.strip()):
                record[field] = int(value.strip())
                value = record[field]
            if value is not None and type(value) is not int:
                raise SkillError("json_fetch", "invalid_integer_field", "JSON %s 必须是整数或 null" % field)
        ut = record["ut"].strip()
        if ut in seen_ut:
            raise SkillError("json_fetch", "duplicate_ut", "JSON 出现重复 UT")
        seen_ut.add(ut)


def main() -> int:
    args = parse_args()
    session = None
    generation: Path | None = None
    outdir: Path | None = None
    stage = "dependencies"
    try:
        if not args.check_access and not args.count_only and args.format == "tsv":
            stage = "prepare_output"
            outdir = Path(args.outdir).expanduser().resolve()
            if outdir.exists():
                raise SkillError(
                    "prepare_output",
                    "output_directory_exists",
                    "输出目录必须是尚不存在的新目录: %s" % outdir,
                )
        stage = "dependencies"
        export_batch, bootstrap, fetch_records_json, run_query = load_backend()
        stage = "bootstrap"
        print("· 自举 WOSCC 会话 …", file=sys.stderr)
        session, sid, origin = bootstrap()
        print("  origin=%s" % origin, file=sys.stderr)

        if args.check_access:
            emit({"ok": True, "mode": "access", "access": True, "origin": origin})
            return 0

        stage = "query"
        qid, found = run_query(session, sid, origin, [{"rowText": args.query}], sort=args.sort)
        target = min(found, args.max)
        print("· WOSCC 命中 %d 条，准备取回 %d 条" % (found, target), file=sys.stderr)

        if args.count_only:
            emit(
                {
                    "ok": True,
                    "mode": "count",
                    "query": args.query,
                    "recordsFound": found,
                    "editions": args.editions,
                    "editionFilterApplied": False,
                    "note": "citation index 需在 TSV 导出后按 WE 过滤" if args.editions else None,
                }
            )
            return 0

        if args.editions and found > target and not args.allow_truncated_edition:
            raise SkillError(
                "query",
                "edition_requires_complete_export",
                (
                    "edition 后过滤要求完整导出当前 WOSCC 候选集；"
                    "recordsFound=%d, requested=%d。请收窄查询或提高 --max；"
                    "只有明确接受截断样本时才使用 --allow-truncated-edition"
                )
                % (found, target),
            )

        if args.format == "json":
            stage = "json_fetch"
            page_size = max(1, min(MAX_JSON, target))
            records = fetch_records_json(
                session, sid, origin, qid, target, sort=args.sort, page_size=page_size
            )
            validate_json_records(records, target)
            emit(
                {
                    "ok": True,
                    "mode": "json",
                    "searchDate": date.today().isoformat(),
                    "query": args.query,
                    "sort": args.sort,
                    "recordsFound": found,
                    "retrieved": len(records),
                    "truncated": found > len(records),
                    "records": records,
                }
            )
            return 0

        stage = "prepare_output"
        assert outdir is not None
        if outdir.exists():
            raise SkillError(
                "prepare_output",
                "output_directory_exists",
                "输出目录必须是尚不存在的新目录: %s" % outdir,
            )
        outdir.parent.mkdir(parents=True, exist_ok=True)
        generation = Path(
            tempfile.mkdtemp(prefix=".%s.partial-" % outdir.name, dir=outdir.parent)
        )
        generation.chmod(0o700)
        paths = [
            generation
            / ("%s_%d-%d.tsv" % (args.prefix, start, min(start + export_batch - 1, target)))
            for start in range(1, target + 1, export_batch)
        ]
        records_jsonl = generation / (args.prefix + "_records.jsonl")

        stage = "export"
        for index, path in enumerate(paths):
            start = index * export_batch + 1
            end = min(start + export_batch - 1, target)
            size = export_tsv(
                session,
                sid,
                origin,
                qid,
                start,
                end,
                args.content,
                path,
                args.sort,
                expected_rows=end - start + 1,
            )
            print("✓ %s (%d bytes)" % (outdir / path.name, size), file=sys.stderr)
            if index + 1 < len(paths):
                time.sleep(1)

        retrieved_raw = target
        filtered_out = 0
        if args.editions:
            stage = "edition_filter"
            kept_total = 0
            total_rows = 0
            wanted = set(args.editions)
            for path in paths:
                kept, total = filter_tsv(path, wanted)
                kept_total += kept
                total_rows += total
            if total_rows != retrieved_raw:
                raise SkillError(
                    "edition_filter",
                    "record_count_mismatch",
                    "导出行数 %d 与预期 %d 不一致" % (total_rows, retrieved_raw),
                )
            filtered_out = retrieved_raw - kept_total

        stage = "normalize"
        normalized = normalize_tsv(paths, records_jsonl)
        expected = retrieved_raw - filtered_out
        if normalized != expected:
            raise SkillError(
                "normalize",
                "record_count_mismatch",
                "规范化 %d 条与 edition 过滤后 %d 条不一致" % (normalized, expected),
            )

        stage = "publish"
        if outdir.exists():
            raise SkillError(
                "publish", "output_directory_race", "发布前输出目录已出现: %s" % outdir
            )
        generation.rename(outdir)
        generation = None
        final_paths = [outdir / path.name for path in paths]
        final_jsonl = outdir / records_jsonl.name
        emit(
            {
                "ok": True,
                "mode": "tsv",
                "searchDate": date.today().isoformat(),
                "query": args.query,
                "sort": args.sort,
                "content": args.content,
                "recordsFound": found,
                "retrievedRaw": retrieved_raw,
                "retrieved": normalized,
                "filteredOut": filtered_out,
                "editions": args.editions,
                "completeWithinWosccQuery": found == retrieved_raw,
                "editionScopeComplete": not args.editions or found == retrieved_raw,
                "editionFilterBasis": (
                    "complete_woscc_candidates"
                    if not args.editions or found == retrieved_raw
                    else "truncated_woscc_prefix"
                ),
                "tsvPaths": [str(path) for path in final_paths],
                "recordsJsonl": str(final_jsonl),
            }
        )
        return 0
    except SkillError as exc:
        payload = {
            "ok": False,
            "stage": exc.stage,
            "code": exc.code,
            "error": sanitize_error(exc),
        }
        if args.check_access:
            payload["access"] = False
        emit(payload)
        return 1
    except Exception as exc:
        payload = {
            "ok": False,
            "stage": stage,
            "code": "unexpected_error",
            "error": sanitize_error(exc),
        }
        if args.check_access:
            payload["access"] = False
        emit(payload)
        return 1
    finally:
        if generation is not None:
            shutil.rmtree(generation, ignore_errors=True)
        if session is not None:
            try:
                session.close()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
