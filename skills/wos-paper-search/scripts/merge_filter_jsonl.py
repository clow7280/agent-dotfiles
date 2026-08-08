#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# ///
"""Merge normalized WOSCC JSONL files, deduplicate, and apply hard filters."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any


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
TERM_FIELDS = {"title", "author_keywords", "keywords_plus", "abstract"}
LIST_FIELDS = {
    "authors",
    "doc_type",
    "author_keywords",
    "keywords_plus",
    "cited_references",
    "wos_index_codes",
}
REQUIRED_FIELDS = {
    "rank",
    "ut",
    "doi",
    "title",
    "authors",
    "source",
    "year",
    "doc_type",
    "author_keywords",
    "keywords_plus",
    "abstract",
    "times_cited_woscc",
    "times_cited_all",
    "cited_references",
    "wos_index",
    "wos_index_codes",
}


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        print(
            json.dumps(
                {"ok": False, "stage": "arguments", "code": "invalid_arguments", "error": message},
                ensure_ascii=False,
            )
        )
        raise SystemExit(2)


class MergeError(RuntimeError):
    def __init__(self, stage: str, code: str, message: str):
        super().__init__(message)
        self.stage = stage
        self.code = code


def parse_named_input(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("--input 必须是 NAME=PATH")
    name, raw_path = value.split("=", 1)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", name):
        raise argparse.ArgumentTypeError("输入名称仅允许 1–40 个字母、数字、下划线或连字符")
    if not raw_path:
        raise argparse.ArgumentTypeError("输入路径不能为空")
    return name, Path(raw_path).expanduser().resolve()


def nonempty_term(value: str) -> str:
    term = value.strip()
    if not term:
        raise argparse.ArgumentTypeError("过滤词不能为空")
    return term


def comma_values(raw: str | None) -> list[str]:
    if raw is None:
        return []
    values = [item.strip() for item in raw.split(",") if item.strip()]
    if not values:
        raise argparse.ArgumentTypeError("逗号分隔列表不能为空")
    return values


def normalize_editions(raw: str | None) -> list[str]:
    values = comma_values(raw)
    normalized: list[str] = []
    unknown: list[str] = []
    for value in values:
        canonical = EDITION_ALIASES.get(value.upper())
        if canonical is None:
            unknown.append(value)
        elif canonical not in normalized:
            normalized.append(canonical)
    if unknown:
        raise argparse.ArgumentTypeError("未知 citation index: %s" % ", ".join(unknown))
    return normalized


def parse_args() -> argparse.Namespace:
    parser = JsonArgumentParser(
        description="合并 WOSCC 规范化 JSONL、按 UT/DOI 去重并执行确定性过滤",
        allow_abbrev=False,
    )
    parser.add_argument("--input", action="append", type=parse_named_input, required=True, help="NAME=PATH，可重复")
    parser.add_argument("--outdir", required=True, help="尚不存在的原子输出目录")
    parser.add_argument("--year-min", type=int)
    parser.add_argument("--year-max", type=int)
    parser.add_argument("--doc-types", help="逗号分隔；任一精确匹配即保留")
    parser.add_argument("--editions", help="逗号分隔，如 SCIE,ESCI；任一精确匹配即保留")
    parser.add_argument("--required-term", action="append", type=nonempty_term, default=[])
    parser.add_argument("--excluded-term", action="append", type=nonempty_term, default=[])
    parser.add_argument(
        "--term-field",
        action="append",
        choices=sorted(TERM_FIELDS),
        dest="term_fields",
        help="词过滤字段，可重复；默认题名、关键词和摘要",
    )
    args = parser.parse_args()

    names = [name for name, _path in args.input]
    if len(names) != len(set(names)):
        parser.error("--input 名称不得重复")
    if args.year_min is not None and args.year_max is not None and args.year_min > args.year_max:
        parser.error("--year-min 不得大于 --year-max")
    try:
        args.doc_types = comma_values(args.doc_types)
        args.editions = normalize_editions(args.editions)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    args.term_fields = args.term_fields or sorted(TERM_FIELDS)
    args.outdir = Path(args.outdir).expanduser().resolve()
    if args.outdir.exists():
        parser.error("--outdir 必须是尚不存在的新目录")
    return args


def optional_string(value: Any) -> bool:
    return value is None or isinstance(value, str)


def validate_record(record: Any, source: Path, line_number: int) -> dict[str, Any]:
    where = "%s:%d" % (source, line_number)
    if not isinstance(record, dict):
        raise MergeError("read", "record_not_object", "%s 记录不是对象" % where)
    missing = sorted(REQUIRED_FIELDS - set(record))
    if missing:
        raise MergeError("read", "missing_fields", "%s 缺少字段: %s" % (where, ",".join(missing)))
    if type(record["rank"]) is not int or record["rank"] < 1:
        raise MergeError("read", "invalid_rank", "%s rank 必须是正整数" % where)
    if not isinstance(record["title"], str) or not record["title"].strip():
        raise MergeError("read", "missing_title", "%s title 不能为空" % where)
    for field in ("ut", "doi", "source", "abstract", "wos_index"):
        if not optional_string(record[field]):
            raise MergeError("read", "invalid_string", "%s %s 类型无效" % (where, field))
    if not (record["ut"] and record["ut"].strip()) and not (record["doi"] and record["doi"].strip()):
        raise MergeError("read", "missing_identity", "%s 同时缺少 UT 和 DOI" % where)
    for field in LIST_FIELDS:
        value = record[field]
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise MergeError("read", "invalid_list", "%s %s 必须是字符串数组" % (where, field))
    for field in ("year", "times_cited_woscc", "times_cited_all"):
        value = record[field]
        if value is not None and type(value) is not int:
            raise MergeError("read", "invalid_integer", "%s %s 必须是整数或 null" % (where, field))
    return dict(record)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise MergeError("read", "input_missing", "输入不存在: %s" % path)
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                raise MergeError("read", "blank_line", "%s:%d 出现空行" % (path, line_number))
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise MergeError("read", "invalid_json", "%s:%d JSON 无效" % (path, line_number)) from exc
            records.append(validate_record(raw, path, line_number))
    return records


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().casefold()
    normalized = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", normalized)
    return normalized or None


def aliases(record: dict[str, Any]) -> list[str]:
    result: list[str] = []
    ut = (record.get("ut") or "").strip().casefold()
    doi = normalize_doi(record.get("doi"))
    if ut:
        result.append("ut:" + ut)
    if doi:
        result.append("doi:" + doi)
    return result


def empty_value(value: Any) -> bool:
    return value is None or value == "" or value == []


def merge_duplicate(base: dict[str, Any], incoming: dict[str, Any], label: str) -> None:
    base_doi = normalize_doi(base.get("doi"))
    incoming_doi = normalize_doi(incoming.get("doi"))
    if base_doi and incoming_doi and base_doi != incoming_doi:
        raise MergeError("merge", "identity_conflict", "同一身份出现冲突 DOI")
    base_ut = (base.get("ut") or "").strip().casefold()
    incoming_ut = (incoming.get("ut") or "").strip().casefold()
    if base_ut and incoming_ut and base_ut != incoming_ut:
        raise MergeError("merge", "identity_conflict", "同一 DOI 对应冲突 UT")
    for field in REQUIRED_FIELDS - {"rank"}:
        if empty_value(base.get(field)) and not empty_value(incoming.get(field)):
            base[field] = incoming[field]
    if label not in base["matched_queries"]:
        base["matched_queries"].append(label)
    base["source_ranks"].setdefault(label, incoming["rank"])


def searchable_text(record: dict[str, Any], fields: list[str]) -> str:
    parts: list[str] = []
    for field in fields:
        value = record.get(field)
        if isinstance(value, list):
            parts.extend(value)
        elif isinstance(value, str):
            parts.append(value)
    return "\n".join(parts).casefold()


def filter_reason(record: dict[str, Any], args: argparse.Namespace) -> str | None:
    year = record.get("year")
    if args.year_min is not None and (year is None or year < args.year_min):
        return "year"
    if args.year_max is not None and (year is None or year > args.year_max):
        return "year"
    if args.doc_types:
        wanted = {value.casefold() for value in args.doc_types}
        present = {value.casefold() for value in record["doc_type"]}
        if not wanted & present:
            return "doc_type"
    if args.editions:
        present = {EDITION_ALIASES.get(value.upper(), value.upper()) for value in record["wos_index_codes"]}
        if not set(args.editions) & present:
            return "edition"
    if args.required_term or args.excluded_term:
        text = searchable_text(record, args.term_fields)
        if any(term.casefold() not in text for term in args.required_term):
            return "required_terms"
        if any(term.casefold() in text for term in args.excluded_term):
            return "excluded_terms"
    return None


def main() -> int:
    args = parse_args()
    generation: Path | None = None
    try:
        input_counts: dict[str, int] = {}
        merged: list[dict[str, Any]] = []
        identity_index: dict[str, int] = {}
        records_read = 0

        for label, path in args.input:
            records = read_jsonl(path)
            input_counts[label] = len(records)
            records_read += len(records)
            seen_in_input: set[int] = set()
            for record in records:
                record_aliases = aliases(record)
                matches = {identity_index[alias] for alias in record_aliases if alias in identity_index}
                if len(matches) > 1:
                    raise MergeError("merge", "identity_bridge_conflict", "UT/DOI 把两个既有记录错误桥接")
                if matches:
                    index = next(iter(matches))
                    if index in seen_in_input:
                        raise MergeError("merge", "duplicate_within_input", "%s 内出现重复身份" % label)
                    merge_duplicate(merged[index], record, label)
                else:
                    index = len(merged)
                    record["matched_queries"] = [label]
                    record["source_ranks"] = {label: record["rank"]}
                    merged.append(record)
                seen_in_input.add(index)
                for alias in aliases(merged[index]):
                    previous = identity_index.get(alias)
                    if previous is not None and previous != index:
                        raise MergeError("merge", "identity_conflict", "身份别名冲突: %s" % alias)
                    identity_index[alias] = index

        filtered_counts = {
            "year": 0,
            "doc_type": 0,
            "edition": 0,
            "required_terms": 0,
            "excluded_terms": 0,
        }
        kept: list[dict[str, Any]] = []
        for record in merged:
            reason = filter_reason(record, args)
            if reason is None:
                record["rank"] = len(kept) + 1
                kept.append(record)
            else:
                filtered_counts[reason] += 1

        outdir: Path = args.outdir
        outdir.parent.mkdir(parents=True, exist_ok=True)
        generation = Path(tempfile.mkdtemp(prefix=".%s.partial-" % outdir.name, dir=outdir.parent))
        generation.chmod(0o700)
        records_path = generation / "merged_records.jsonl"
        report_path = generation / "merge_report.json"
        with records_path.open("x", encoding="utf-8", newline="\n") as destination:
            for record in kept:
                destination.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        report = {
            "ok": True,
            "mode": "merge_filter",
            "inputCounts": input_counts,
            "recordsRead": records_read,
            "uniqueBeforeFilters": len(merged),
            "duplicatesRemoved": records_read - len(merged),
            "filtered": filtered_counts,
            "kept": len(kept),
            "filters": {
                "yearMin": args.year_min,
                "yearMax": args.year_max,
                "docTypesAny": args.doc_types,
                "editionsAny": args.editions,
                "requiredTermsAll": args.required_term,
                "excludedTermsAny": args.excluded_term,
                "termFields": args.term_fields,
            },
        }
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if outdir.exists():
            raise MergeError("publish", "output_directory_race", "发布前输出目录已出现")
        generation.rename(outdir)
        generation = None
        report["recordsJsonl"] = str(outdir / records_path.name)
        report["reportJson"] = str(outdir / report_path.name)
        print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
        return 0
    except MergeError as exc:
        print(
            json.dumps(
                {"ok": False, "stage": exc.stage, "code": exc.code, "error": str(exc)[:1000]},
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        return 1
    except Exception as exc:
        print(
            json.dumps(
                {"ok": False, "stage": "unexpected", "code": "unexpected_error", "error": str(exc)[:1000]},
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        return 1
    finally:
        if generation is not None:
            shutil.rmtree(generation, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
