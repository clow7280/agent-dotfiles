#!/usr/bin/env python3
"""Conservative structural lint for GB/T 7714—2025 text.

The utility reports issues and review prompts; it never rewrites references or
invents metadata.  Semantic classification remains the calling agent's job.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Sequence


TYPE_CODES = {
    "M", "J", "N", "C", "D", "R", "S", "P", "EB", "A", "CM",
    "DS", "PP", "G", "CP", "DB", "Z",
}
CARRIER_CODES = {"MT", "DK", "CD", "OL", "MM"}
ACCESS_DATE_TYPES = {"EB", "DS", "PP"}
CONTEXTUAL_WEB_TYPES = {"CP", "DB", "Z"}
MAX_CITATION_RANGE = 10_000
MAX_CITATION_MEMBERS = 10_000
MAX_TOTAL_CITATION_NUMBERS = 100_000
MAX_CITATION_NUMBER = 10_000_000

HEADING_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:参考文献|references|bibliography)\s*[:：]?\s*$",
    re.IGNORECASE,
)
GROUP_LABEL_RE = re.compile(
    r"^\s*(?:中文|汉文|日文|西文|英文|俄文|其他语种)(?:参考)?文献\s*[:：]?\s*$",
    re.IGNORECASE,
)
REF_START_RE = re.compile(
    r"^\s*(?:[-*+]\s+)?[［\[]\s*(\d+)\s*[］\]]\s*(.*)$"
)
AUTHOR_ENTRY_START_RE = re.compile(
    r"^\s*(?:[-*+]\s+)?(?P<author>.+?)[,，]\s*"
    r"(?P<year>\[?(?:c)?\d{4}[a-z]?\]?)\s*[.．]\s*(?P<rest>\S.*)$",
    re.IGNORECASE,
)
NUMERIC_LIKE_ENTRY_RE = re.compile(
    r"^\s*(?:[-*+]\s+)?(?:[［\[]\s*-?[0-9]+\s*[］\]]|[0-9]+\s*[.．、)])"
)
TAG_RE = re.compile(
    r"[［\[]\s*([A-Za-z0-9]{1,3})(?:\s*/\s*([A-Za-z0-9]{1,3}))?\s*[］\]]"
)
CITATION_RE = re.compile(
    r"[［\[]\s*\d+(?:\s*[,，;；\-–—]\s*\d+)*\s*[］\]]"
)
SUSPICIOUS_PAGE_CITE_RE = re.compile(
    r"[［\[]\s*(\d+)\s*[,，]\s*(?:p{1,2}\.?|页)\s*"
    r"\d+(?:\s*[-–—]\s*\d+)?\s*[］\]]",
    re.IGNORECASE,
)
COLON_PAGE_CITE_RE = re.compile(
    r"[［\[]\s*(\d+)\s*[:：]\s*\d+(?:\s*[-–—]\s*\d+)?\s*[］\]]"
)
DATE_BRACKET_RE = re.compile(
    r"[［\[]\s*(\d{4}[-/.]\d{1,2}[-/.]\d{1,2})\s*[］\]]"
)
DATE_BRACKET_FULL_RE = re.compile(
    r"^[［\[]\s*\d{4}[-/.]\d{1,2}[-/.]\d{1,2}\s*[］\]]$"
)
DATE_PAREN_RE = re.compile(
    r"[（(]\s*(\d{4}[-/.]\d{1,2}[-/.]\d{1,2})\s*[）)]"
)
AUTHOR_DATE_RE = re.compile(
    r"[（(][^()（）\n]{1,100}?[,，]\s*\d{4}[a-z]?[）)]",
    re.IGNORECASE,
)
URL_RE = re.compile(r"(?:https?|ftp)://\S+", re.IGNORECASE)
ACCESS_PATH_RE = re.compile(
    r"(?:(?:https?|ftp)://|urn:|doi:\s*10\.|(?<!\d)10\.\d{4,9}/)\S+",
    re.IGNORECASE,
)
STANDARD_NUMBER_RE = re.compile(
    r"^\s*(?:(?:GB(?:/T|/Z)?|GBZ(?:/T)?|ISO(?:/IEC)?|IEC|IEEE|ANSI|ASTM|"
    r"DIN|BS|EN|T/[A-Z0-9]+|[A-Z]{1,8}[0-9]{0,4}/[A-Z0-9]{1,8})\s*)\d",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Entry:
    number: int | None
    line: int
    text: str
    author: str | None = None
    year: str | None = None


@dataclass(frozen=True)
class Citation:
    line: int
    raw: str
    numbers: tuple[int, ...]


@dataclass(frozen=True)
class Diagnostic:
    severity: str
    code: str
    message: str
    line: int | None = None
    entry: int | None = None


def read_input(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8-sig")


def find_reference_heading(lines: Sequence[str]) -> int | None:
    matches = [i for i, line in enumerate(lines) if HEADING_RE.match(line)]
    return matches[-1] if matches else None


def bounded_number(token: str) -> int | None:
    """Convert an ASCII integer without triggering Python's huge-int guard."""
    if not re.fullmatch(r"[0-9]+", token):
        return None
    normalized = token.lstrip("0") or "0"
    limit = str(MAX_CITATION_NUMBER)
    if len(normalized) > len(limit) or (
        len(normalized) == len(limit) and normalized > limit
    ):
        return None
    return int(normalized)


def extract_numeric_entries(lines: Sequence[str], heading: int | None) -> list[Entry]:
    start = heading + 1 if heading is not None else 0
    entries: list[Entry] = []
    current_number: int | None = None
    current_line: int | None = None
    parts: list[str] = []

    def flush() -> None:
        nonlocal current_number, current_line, parts
        if current_number is not None and current_line is not None:
            text = " ".join(part for part in parts if part).strip()
            entries.append(Entry(current_number, current_line, text))
        current_number = None
        current_line = None
        parts = []

    for index in range(start, len(lines)):
        line = lines[index]
        match = REF_START_RE.match(line)
        if match:
            flush()
            parsed_number = bounded_number(match.group(1))
            current_number = (
                parsed_number
                if parsed_number is not None
                else MAX_CITATION_NUMBER + 1
            )
            current_line = index + 1
            parts = [match.group(2).strip()]
            continue
        if current_number is not None:
            if heading is not None and re.match(r"^\s*#{1,6}\s+\S", line):
                flush()
                break
            stripped = line.strip()
            if stripped and not GROUP_LABEL_RE.match(stripped):
                parts.append(stripped)
    flush()
    return entries


def extract_author_date_entries(
    lines: Sequence[str], heading: int | None, *, allow_without_heading: bool = False
) -> tuple[list[Entry], list[int]]:
    """Parse unnumbered `author, year.title...` entries after a heading."""
    if heading is None and not allow_without_heading:
        return [], []

    entries: list[Entry] = []
    unparsed_lines: list[int] = []
    current_line: int | None = None
    current_author: str | None = None
    current_year: str | None = None
    parts: list[str] = []

    def flush() -> None:
        nonlocal current_line, current_author, current_year, parts
        if current_line is not None:
            entries.append(
                Entry(
                    None,
                    current_line,
                    " ".join(part for part in parts if part).strip(),
                    current_author,
                    current_year,
                )
            )
        current_line = None
        current_author = None
        current_year = None
        parts = []

    start = heading + 1 if heading is not None else 0
    for index in range(start, len(lines)):
        line = lines[index]
        if re.match(r"^\s*#{1,6}\s+\S", line):
            if current_line is not None or heading is not None:
                flush()
                break
            unparsed_lines.append(index + 1)
            continue
        match = AUTHOR_ENTRY_START_RE.match(line)
        if match:
            flush()
            current_line = index + 1
            current_author = match.group("author").strip()
            current_year = match.group("year").strip()
            parts = [line.strip().lstrip("-*+ ")]
            continue
        stripped = line.strip()
        if not stripped or GROUP_LABEL_RE.match(stripped):
            continue
        if current_line is not None:
            parts.append(stripped)
        elif not REF_START_RE.match(line):
            unparsed_lines.append(index + 1)
    flush()
    return entries, unparsed_lines


def parse_citation(raw: str) -> tuple[tuple[int, ...], str | None, str | None]:
    inner = raw.strip("[]［］ ")
    if ";" in inner or "；" in inner:
        return (), "CITE_SYNTAX", "同处多篇顺序编码应使用逗号，而不是分号"

    numbers: list[int] = []
    for part in re.split(r"[,，]", inner):
        part = part.strip()
        range_match = re.fullmatch(r"(\d+)\s*[-–—]\s*(\d+)", part)
        if range_match:
            first = bounded_number(range_match.group(1))
            last = bounded_number(range_match.group(2))
            if first is not None and last is None:
                return (
                    (),
                    "CITE_RANGE_TOO_LARGE",
                    f"连续序号范围起于 {first}，终值超过安全上限 {MAX_CITATION_NUMBER}；未展开",
                )
            if first is None or last is None:
                return (
                    (),
                    "CITE_NUMBER_TOO_LARGE",
                    f"引文序号超过安全上限 {MAX_CITATION_NUMBER}",
                )
            if first <= 0 or last <= 0:
                return (), "CITE_NUMBER_INVALID", "引文序号应为正整数"
            if first > last:
                return (), "CITE_SYNTAX", f"倒置的连续序号范围 {first}-{last}"
            width = last - first + 1
            if width > MAX_CITATION_RANGE or len(numbers) + width > MAX_CITATION_MEMBERS:
                return (
                    (),
                    "CITE_RANGE_TOO_LARGE",
                    f"连续序号范围 {first}-{last} 过大，未展开；单组上限为 {MAX_CITATION_MEMBERS}",
                )
            numbers.extend(range(first, last + 1))
        elif part.isdigit():
            number = bounded_number(part)
            if number is None:
                return (
                    (),
                    "CITE_NUMBER_TOO_LARGE",
                    f"引文序号超过安全上限 {MAX_CITATION_NUMBER}",
                )
            if number <= 0:
                return (), "CITE_NUMBER_INVALID", "引文序号应为正整数"
            numbers.append(number)
            if len(numbers) > MAX_CITATION_MEMBERS:
                return (
                    (),
                    "CITE_RANGE_TOO_LARGE",
                    f"单组引文超过安全上限 {MAX_CITATION_MEMBERS}",
                )
        else:
            return (), "CITE_SYNTAX", f"无法解析的顺序编码 {part!r}"
    return tuple(numbers), None, None


def extract_citations(
    lines: Sequence[str], body_end: int
) -> tuple[list[Citation], list[Diagnostic], bool]:
    citations: list[Citation] = []
    diagnostics: list[Diagnostic] = []
    total_numbers = 0
    parse_complete = True
    limit_reported = False

    def append_citation(citation: Citation) -> None:
        nonlocal total_numbers, parse_complete, limit_reported
        width = len(citation.numbers)
        if total_numbers + width > MAX_TOTAL_CITATION_NUMBERS:
            parse_complete = False
            if not limit_reported:
                diagnostics.append(
                    Diagnostic(
                        "error",
                        "CITATION_TOTAL_LIMIT",
                        f"全文展开后的引文序号超过安全上限 {MAX_TOTAL_CITATION_NUMBERS}；已停止收集并跳过闭环结论",
                        citation.line,
                    )
                )
                limit_reported = True
            return
        citations.append(citation)
        total_numbers += width

    for index, line in enumerate(lines[:body_end]):
        for regex in (SUSPICIOUS_PAGE_CITE_RE, COLON_PAGE_CITE_RE):
            for match in regex.finditer(line):
                number = bounded_number(match.group(1))
                if number is None:
                    parse_complete = False
                    diagnostics.append(
                        Diagnostic(
                            "error",
                            "CITE_NUMBER_TOO_LARGE",
                            f"引文序号超过安全上限 {MAX_CITATION_NUMBER}",
                            index + 1,
                        )
                    )
                elif number <= 0:
                    parse_complete = False
                    diagnostics.append(
                        Diagnostic(
                            "error",
                            "CITE_NUMBER_INVALID",
                            "引文序号应为正整数",
                            index + 1,
                        )
                    )
                else:
                    append_citation(Citation(index + 1, match.group(0), (number,)))
                diagnostics.append(
                    Diagnostic(
                        "error",
                        "PAGE_INSIDE_CITATION",
                        "复引页码应置于右方括号外，不应写在序号括号内："
                        + match.group(0),
                        index + 1,
                    )
                )
        for match in CITATION_RE.finditer(line):
            raw = match.group(0)
            # A bracketed full date is a date token, not a numeric citation.
            if DATE_BRACKET_FULL_RE.fullmatch(raw):
                continue
            numbers, code, error = parse_citation(raw)
            if error:
                parse_complete = False
                diagnostics.append(Diagnostic("error", code or "CITE_SYNTAX", error, index + 1))
            else:
                append_citation(Citation(index + 1, raw, numbers))
    return citations, diagnostics, parse_complete


def extract_tag(entry: Entry) -> tuple[str, str | None] | None:
    for match in TAG_RE.finditer(entry.text):
        type_code = match.group(1)
        carrier = match.group(2)
        if any(ch.isalpha() for ch in type_code + (carrier or "")):
            return type_code.upper(), carrier.upper() if carrier else None
    return None


def looks_like_standard(entry: Entry) -> bool:
    return bool(STANDARD_NUMBER_RE.match(entry.text))


def add_date_diagnostics(entries: Sequence[Entry], diagnostics: list[Diagnostic]) -> None:
    for entry in entries:
        for regex, role in (
            (DATE_BRACKET_RE, "引用日期"),
            (DATE_PAREN_RE, "创建/发布/修改日期"),
        ):
            for match in regex.finditer(entry.text):
                value = match.group(1)
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                    diagnostics.append(
                        Diagnostic(
                            "error",
                            "DATE_FORMAT",
                            f"{role}应使用 YYYY-MM-DD：{value}",
                            entry.line,
                            entry.number,
                        )
                    )
                    continue
                try:
                    date.fromisoformat(value)
                except ValueError:
                    diagnostics.append(
                        Diagnostic(
                            "error",
                            "DATE_INVALID",
                            f"{role}不是有效的公历日期：{value}",
                            entry.line,
                            entry.number,
                        )
                    )


def _add_numbering_diagnostics(
    entries: Sequence[Entry],
    diagnostics: list[Diagnostic],
    *,
    require_start_at_one: bool,
) -> None:
    numbered = [entry for entry in entries if entry.number is not None]
    seen: dict[int, int] = {}
    for entry in numbered:
        assert entry.number is not None
        if entry.number in seen:
            diagnostics.append(
                Diagnostic(
                    "error",
                    "REF_DUPLICATE_NUMBER",
                    f"参考文献序号 {entry.number} 重复；首次见于第 {seen[entry.number]} 行",
                    entry.line,
                    entry.number,
                )
            )
        else:
            seen[entry.number] = entry.line
        if entry.number <= 0:
            diagnostics.append(
                Diagnostic(
                    "error",
                    "REF_NUMBER_INVALID",
                    "参考文献序号应为正整数",
                    entry.line,
                    entry.number,
                )
            )
        if entry.number > MAX_CITATION_NUMBER:
            diagnostics.append(
                Diagnostic(
                    "error",
                    "REF_NUMBER_TOO_LARGE",
                    f"参考文献序号超过安全上限 {MAX_CITATION_NUMBER}",
                    entry.line,
                    entry.number,
                )
            )

    if not numbered:
        return
    numbers = [entry.number for entry in numbered]
    unique_sorted = sorted(set(number for number in numbers if number is not None))
    gap_count = 0
    gap_examples: list[int] = []
    previous = 0 if require_start_at_one else unique_sorted[0]
    numbers_to_check = unique_sorted if require_start_at_one else unique_sorted[1:]
    for number in numbers_to_check:
        width = number - previous - 1
        if width > 0:
            gap_count += width
            room = max(0, 20 - len(gap_examples))
            gap_examples.extend(range(previous + 1, min(number, previous + 1 + room)))
        previous = number
    if gap_count:
        sample = ", ".join(map(str, gap_examples))
        suffix = "" if gap_count <= len(gap_examples) else f"（仅列前 {len(gap_examples)} 个，共 {gap_count} 个）"
        diagnostics.append(
            Diagnostic(
                "error",
                "REF_NUMBER_GAP",
                f"参考文献序号不连续，缺少：{sample}{suffix}",
                numbered[0].line,
            )
        )
    if numbers != sorted(numbers):
        diagnostics.append(
            Diagnostic(
                "error",
                "REF_NUMBER_ORDER",
                "参考文献表序号未按升序排列",
                numbered[0].line,
            )
        )


def audit_entries(
    entries: Sequence[Entry],
    diagnostics: list[Diagnostic],
    *,
    numbered: bool,
    complete_numbered_list: bool,
    standardization_document: bool,
    web_context: bool,
) -> None:
    if numbered:
        _add_numbering_diagnostics(
            entries,
            diagnostics,
            require_start_at_one=complete_numbered_list,
        )

    for entry in entries:
        tag = extract_tag(entry)
        if tag is None:
            if looks_like_standard(entry):
                if not standardization_document:
                    diagnostics.append(
                        Diagnostic(
                            "warning",
                            "STANDARD_TYPE_CONTEXT",
                            "标准条目未写 [S]；标准化文件中允许省略，其他文档中为必备，请确认宿主文档语境",
                            entry.line,
                            entry.number,
                        )
                    )
                if URL_RE.search(entry.text):
                    diagnostics.append(
                        Diagnostic(
                            "error",
                            "CARRIER_MISSING",
                            "标准化文件中 [S] 可省略，但电子标准的载体标识仍为必备；条目含 URL 却未识别到载体",
                            entry.line,
                            entry.number,
                        )
                    )
                continue
            diagnostics.append(
                Diagnostic(
                    "error",
                    "TYPE_MISSING",
                    "未识别到文献类型标识",
                    entry.line,
                    entry.number,
                )
            )
            continue

        type_code, carrier = tag
        if type_code not in TYPE_CODES:
            diagnostics.append(
                Diagnostic(
                    "error",
                    "TYPE_INVALID",
                    f"附录 A 中不存在文献类型代码 {type_code}",
                    entry.line,
                    entry.number,
                )
            )
        if carrier is not None and carrier not in CARRIER_CODES:
            diagnostics.append(
                Diagnostic(
                    "error",
                    "CARRIER_INVALID",
                    f"附录 A 中不存在载体代码 {carrier}",
                    entry.line,
                    entry.number,
                )
            )

        if type_code == "EB" and carrier is None:
            diagnostics.append(
                Diagnostic(
                    "error",
                    "CARRIER_MISSING",
                    "网站/网页是电子资源，必须同时著录载体代码",
                    entry.line,
                    entry.number,
                )
            )

        has_url = bool(URL_RE.search(entry.text))
        has_access_path = bool(ACCESS_PATH_RE.search(entry.text))
        if carrier == "OL" and not has_access_path:
            diagnostics.append(
                Diagnostic(
                    "error",
                    "OL_PATH_MISSING",
                    "联机资源标为 /OL，但未识别到获取和访问路径",
                    entry.line,
                    entry.number,
                )
            )
        elif carrier in CARRIER_CODES - {"OL"} and not has_access_path:
            diagnostics.append(
                Diagnostic(
                    "warning",
                    "ELECTRONIC_PATH_UNRECOGNIZED",
                    f"电子载体 /{carrier} 的获取和访问路径未能由文本预检识别，请人工核对",
                    entry.line,
                    entry.number,
                )
            )
        if has_url and carrier is None and type_code != "EB":
            diagnostics.append(
                Diagnostic(
                    "warning",
                    "URL_WITHOUT_CARRIER",
                    "条目含 URL，但类型标识没有载体代码；请核对是否应为 /OL",
                    entry.line,
                    entry.number,
                )
            )

        has_access_date_token = bool(DATE_BRACKET_RE.search(entry.text))
        access_date_required = type_code in ACCESS_DATE_TYPES or (
            web_context and carrier == "OL"
        )
        if access_date_required and not has_access_date_token:
            diagnostics.append(
                Diagnostic(
                    "error",
                    "ACCESS_DATE_MISSING",
                    f"{type_code} 条目在当前模板语境下缺少必备引用日期 [YYYY-MM-DD]",
                    entry.line,
                    entry.number,
                )
            )
        elif (
            not web_context
            and type_code in CONTEXTUAL_WEB_TYPES
            and carrier == "OL"
            and not has_access_date_token
        ):
            diagnostics.append(
                Diagnostic(
                    "warning",
                    "ACCESS_DATE_CONTEXT",
                    f"{type_code}/OL 若按 8.11 的网站/网页形态著录，引用日期为必备；请确认模板语境，或使用 --web-context",
                    entry.line,
                    entry.number,
                )
            )


def audit_author_date_keys(entries: Sequence[Entry], diagnostics: list[Diagnostic]) -> None:
    groups: dict[tuple[str, str], list[Entry]] = {}
    for entry in entries:
        if not entry.author or not entry.year:
            continue
        author_key = re.sub(r"[\W_]+", "", entry.author, flags=re.UNICODE).casefold()
        match = re.search(r"\d{4}", entry.year)
        if match:
            groups.setdefault((author_key, match.group(0)), []).append(entry)
    for (_, year), group in groups.items():
        if len(group) < 2:
            continue
        suffixes = [re.search(r"([a-z])(?=\]?$)", entry.year or "", re.I) for entry in group]
        if any(match is None for match in suffixes):
            diagnostics.append(
                Diagnostic(
                    "error",
                    "AUTHOR_YEAR_SUFFIX_MISSING",
                    f"同一责任者在 {year} 年有多条文献，年份应使用 a/b/c 后缀并与正文同步",
                    group[0].line,
                )
            )
            continue
        values = [match.group(1).lower() for match in suffixes if match]
        if len(values) != len(set(values)):
            diagnostics.append(
                Diagnostic(
                    "error",
                    "AUTHOR_YEAR_SUFFIX_DUPLICATE",
                    f"同一责任者 {year} 年的消歧后缀重复",
                    group[0].line,
                )
            )


def audit_cross_links(
    entries: Sequence[Entry], citations: Sequence[Citation], diagnostics: list[Diagnostic]
) -> None:
    entry_lines = {
        entry.number: entry.line for entry in entries if entry.number is not None
    }
    citation_lines: dict[int, int] = {}
    for citation in citations:
        for number in citation.numbers:
            citation_lines.setdefault(number, citation.line)

    ref_numbers = set(entry_lines)
    cited_numbers = set(citation_lines)
    for number in sorted(cited_numbers - ref_numbers):
        diagnostics.append(
            Diagnostic(
                "error",
                "CITATION_WITHOUT_REFERENCE",
                f"正文引用 {number} 没有对应的参考文献条目",
                citation_lines[number],
                number,
            )
        )
    for number in sorted(ref_numbers - cited_numbers):
        diagnostics.append(
            Diagnostic(
                "warning",
                "REFERENCE_NOT_CITED",
                f"条目 {number} 未在正文中检出；若属阅读型参考文献则可保留",
                entry_lines[number],
                number,
            )
        )

    first_seen: list[int] = []
    seen: set[int] = set()
    for citation in citations:
        for number in citation.numbers:
            if number not in seen:
                seen.add(number)
                first_seen.append(number)
    if first_seen and first_seen != list(range(1, len(first_seen) + 1)):
        diagnostics.append(
            Diagnostic(
                "error",
                "FIRST_APPEARANCE_ORDER",
                "正文中新文献的首次出现顺序不是从 1 开始连续递增："
                + ", ".join(map(str, first_seen[:50]))
                + (" …" if len(first_seen) > 50 else ""),
            )
        )


def infer_system(
    text: str,
    numeric_entries: Sequence[Entry],
    author_entries: Sequence[Entry],
    citations: Sequence[Citation],
) -> str:
    if numeric_entries:
        return "numeric"
    if author_entries:
        return "author-date"
    if citations:
        return "numeric"
    if AUTHOR_DATE_RE.search(text):
        return "author-date"
    return "unknown"


def lint(
    text: str,
    requested_system: str,
    *,
    standardization_document: bool = False,
    web_context: bool = False,
) -> dict[str, object]:
    lines = text.splitlines()
    heading = find_reference_heading(lines)
    numeric_entries = extract_numeric_entries(lines, heading)
    reference_content_lines = (
        [
            index + 1
            for index, line in enumerate(lines[heading + 1 :], start=heading + 1)
            if line.strip()
            and not GROUP_LABEL_RE.match(line)
            and not re.match(r"^\s*#{1,6}\s+\S", line)
        ]
        if heading is not None
        else []
    )
    strong_author_fragment = heading is None and any(
        AUTHOR_ENTRY_START_RE.match(line) for line in lines if line.strip()
    )
    author_entries, unparsed_author_lines = extract_author_date_entries(
        lines,
        heading,
        allow_without_heading=(
            requested_system == "author-date"
            or (requested_system == "auto" and strong_author_fragment)
        ),
    )
    numeric_like_lines = (
        [
            line_number
            for line_number in reference_content_lines
            if NUMERIC_LIKE_ENTRY_RE.match(lines[line_number - 1])
        ]
        if not numeric_entries
        else []
    )

    if heading is not None:
        body_end = heading
    elif numeric_entries:
        body_end = max(0, numeric_entries[0].line - 1)
    else:
        body_end = len(lines)
    has_body_content = any(line.strip() for line in lines[:body_end])
    citations, diagnostics, citation_parse_complete = extract_citations(lines, body_end)
    if requested_system == "auto":
        system = infer_system(text, numeric_entries, author_entries, citations)
        if system == "unknown" and numeric_like_lines:
            system = "numeric"
    else:
        system = requested_system

    if system == "author-date" and numeric_entries:
        entries = numeric_entries
        numbered = True
        diagnostics.append(
            Diagnostic(
                "error",
                "AUTHOR_DATE_NUMBERED_LIST",
                "著者-出版年制参考文献表不应带顺序编码",
                numeric_entries[0].line,
            )
        )
    elif system == "numeric" and not numeric_entries and author_entries:
        entries = author_entries
        numbered = False
        diagnostics.append(
            Diagnostic(
                "error",
                "NUMERIC_UNNUMBERED_LIST",
                "顺序编码制参考文献表缺少方括号序号",
                author_entries[0].line,
            )
        )
    elif system == "author-date":
        entries = author_entries
        numbered = False
    else:
        entries = numeric_entries
        numbered = bool(numeric_entries)

    add_date_diagnostics(entries, diagnostics)
    audit_entries(
        entries,
        diagnostics,
        numbered=numbered,
        complete_numbered_list=(heading is not None),
        standardization_document=standardization_document,
        web_context=web_context,
    )

    if (
        heading is not None
        and numeric_entries
        and system == "numeric"
        and citation_parse_complete
        and has_body_content
    ):
        audit_cross_links(numeric_entries, citations, diagnostics)
    elif (
        heading is not None
        and numeric_entries
        and system == "numeric"
        and has_body_content
    ):
        diagnostics.append(
            Diagnostic(
                "warning",
                "CROSS_LINK_SKIPPED",
                "正文引文未能完整解析，已跳过正文—文后表闭环检查，以免产生未引用/悬空误报",
            )
        )
    if system == "author-date":
        if author_entries:
            audit_author_date_keys(author_entries, diagnostics)
        elif not numeric_entries and (heading is not None or unparsed_author_lines):
            diagnostics.append(
                Diagnostic(
                    "error",
                    "AUTHOR_DATE_ENTRIES_UNPARSED",
                    "未能解析著者—出版年制文后条目；请检查“责任者, 年.题名”结构",
                    unparsed_author_lines[0] if unparsed_author_lines else heading + 2,
                )
            )
        if citations:
            diagnostics.append(
                Diagnostic(
                    "warning",
                    "MIXED_NUMERIC_CITATION",
                    "目标为著者—出版年制，但正文检出方括号数字引文",
                    citations[0].line,
                )
            )
    if (
        system == "numeric"
        and not numeric_entries
        and not author_entries
        and reference_content_lines
    ):
        diagnostics.append(
            Diagnostic(
                "error",
                "NUMERIC_ENTRIES_UNPARSED",
                "参考文献标题后存在内容，但未能解析方括号正整数序号条目",
                numeric_like_lines[0] if numeric_like_lines else reference_content_lines[0],
            )
        )

    diagnostics.sort(key=lambda item: ((item.line or 0), item.code, item.entry or 0))
    return {
        "system": system,
        "reference_heading_found": heading is not None,
        "reference_entries": len(entries),
        "body_citation_groups": len(citations),
        "errors": sum(item.severity == "error" for item in diagnostics),
        "warnings": sum(item.severity == "warning" for item in diagnostics),
        "diagnostics": [asdict(item) for item in diagnostics],
    }


def format_text(result: dict[str, object]) -> str:
    lines = [
        f"体系: {result['system']}",
        f"参考文献条目: {result['reference_entries']}",
        f"正文引文组: {result['body_citation_groups']}",
        f"错误: {result['errors']}；警告: {result['warnings']}",
    ]
    diagnostics = result["diagnostics"]
    if not diagnostics:
        lines.append("未检出脚本覆盖范围内的确定性结构问题。仍需进行语义审校。")
        return "\n".join(lines)
    lines.append("")
    for item in diagnostics:  # type: ignore[assignment]
        location: list[str] = []
        if item["line"] is not None:
            location.append(f"行 {item['line']}")
        if item["entry"] is not None:
            location.append(f"条目 {item['entry']}")
        where = f" ({', '.join(location)})" if location else ""
        lines.append(
            f"[{item['severity'].upper()} {item['code']}]{where} {item['message']}"
        )
    return "\n".join(lines)


def diagnostic_codes(result: dict[str, object]) -> set[str]:
    return {item["code"] for item in result["diagnostics"]}  # type: ignore[index]


def run_self_test() -> None:
    clean = """正文先引文[1]，再合引[2-3]。

参考文献
[1] 李明.示例图书[M].北京:示例出版社,2024.
[2] 王华.示例网页[EB/OL].(2025-01-02)[2025-07-16].https://example.org/page.
[3] Zhao Q. Example article[J/OL]. Journal,2025,2(1):7.https://example.org/a.
"""
    assert lint(clean, "auto")["errors"] == 0

    broken = """正文引用[2]。

参考文献
[1] 李明.网页[EB/0L].https://example.org.
[3] 王华.图书[M].北京:示例出版社,2024.
"""
    broken_codes = diagnostic_codes(lint(broken, "auto"))
    assert {"CARRIER_INVALID", "REF_NUMBER_GAP", "CITATION_WITHOUT_REFERENCE"} <= broken_codes

    page_inside = """正文复引[1, p. 18]，另一次写成[1:260]。

参考文献
[1] 李明.示例图书[M].北京:示例出版社,2024.
"""
    page_result = lint(page_inside, "numeric")
    assert "PAGE_INSIDE_CITATION" in diagnostic_codes(page_result)
    assert "REFERENCE_NOT_CITED" not in diagnostic_codes(page_result)

    date_in_body = """普通日期[2025-07-16]与正文引文[1]。

参考文献
[1] 李明.示例图书[M].北京:示例出版社,2024.
"""
    date_result = lint(date_in_body, "numeric")
    assert "CITE_SYNTAX" not in diagnostic_codes(date_result)
    assert date_result["body_citation_groups"] == 1

    author_date = """参考文献
张三, 2025. 示例网页[EB/OL].https://example.org.
"""
    author_result = lint(author_date, "author-date")
    assert author_result["reference_entries"] == 1
    assert "ACCESS_DATE_MISSING" in diagnostic_codes(author_result)

    author_fragment = "张三, 2025. 示例网页[EB/OL].https://example.org."
    fragment_result = lint(author_fragment, "author-date")
    assert fragment_result["reference_entries"] == 1
    assert "ACCESS_DATE_MISSING" in diagnostic_codes(fragment_result)
    auto_fragment_result = lint(author_fragment, "auto")
    assert auto_fragment_result["system"] == "author-date"
    assert auto_fragment_result["reference_entries"] == 1

    malformed_fragment = "张三. 示例网页[EB/OL].https://example.org."
    assert "AUTHOR_DATE_ENTRIES_UNPARSED" in diagnostic_codes(
        lint(malformed_fragment, "author-date")
    )

    optional_standard = """参考文献
[1] GB/T 1234—2025 示例标准
"""
    standard_result = lint(optional_standard, "numeric")
    assert "TYPE_MISSING" not in diagnostic_codes(standard_result)
    assert "STANDARD_TYPE_CONTEXT" in diagnostic_codes(standard_result)
    standardized_result = lint(
        optional_standard, "numeric", standardization_document=True
    )
    assert "STANDARD_TYPE_CONTEXT" not in diagnostic_codes(standardized_result)

    local_standard = """参考文献
[1] DB11/T 1234—2025 示例地方标准
"""
    local_result = lint(
        local_standard, "numeric", standardization_document=True
    )
    assert "TYPE_MISSING" not in diagnostic_codes(local_result)

    online_standard = """参考文献
[1] GB/T 1234—2025 示例标准.https://example.org/std
"""
    assert "CARRIER_MISSING" in diagnostic_codes(
        lint(online_standard, "numeric", standardization_document=True)
    )

    invalid_dates = """参考文献
[1] 示例网页[EB/OL].(2025-13-40)[2025-02-31].https://example.org.
"""
    invalid_result = lint(invalid_dates, "numeric")
    assert "DATE_INVALID" in diagnostic_codes(invalid_result)

    slash_body = """正文普通日期[2025/7/6]，引用[1]。

参考文献
[1] 示例图书[M].北京:示例出版社,2024.
"""
    assert "DATE_FORMAT" not in diagnostic_codes(lint(slash_body, "numeric"))

    slash_reference = """参考文献
[1] 示例网页[EB/OL].[2025/7/6].https://example.org.
"""
    assert "DATE_FORMAT" in diagnostic_codes(lint(slash_reference, "numeric"))

    huge_range = """正文异常引文[1-999999999]。

参考文献
[1] 示例图书[M].北京:示例出版社,2024.
"""
    huge_result = lint(huge_range, "numeric")
    assert "CITE_RANGE_TOO_LARGE" in diagnostic_codes(huge_result)
    assert "REFERENCE_NOT_CITED" not in diagnostic_codes(huge_result)
    assert "CROSS_LINK_SKIPPED" in diagnostic_codes(huge_result)

    total_heavy = "正文" + "".join("[1-10000]" for _ in range(11)) + "。\n\n参考文献\n[1] 示例图书[M]."
    total_result = lint(total_heavy, "numeric")
    assert "CITATION_TOTAL_LIMIT" in diagnostic_codes(total_result)
    assert "REFERENCE_NOT_CITED" not in diagnostic_codes(total_result)

    huge_gap = """参考文献
[1] 示例图书[M].
[999999999] 另一图书[M].
"""
    assert "REF_NUMBER_GAP" in diagnostic_codes(lint(huge_gap, "numeric"))

    numeric_fragment = "[50] 示例图书[M]."
    assert "REF_NUMBER_GAP" not in diagnostic_codes(
        lint(numeric_fragment, "numeric")
    )

    malformed_numeric = """参考文献
1. 示例图书[M].
"""
    assert "NUMERIC_ENTRIES_UNPARSED" in diagnostic_codes(
        lint(malformed_numeric, "auto")
    )

    enormous_digits = "9" * 5000
    enormous_cite = f"正文[{enormous_digits}]。\n\n参考文献\n[1] 示例图书[M]."
    assert "CITE_NUMBER_TOO_LARGE" in diagnostic_codes(
        lint(enormous_cite, "numeric")
    )
    enormous_ref = f"参考文献\n[{enormous_digits}] 示例图书[M]."
    assert "REF_NUMBER_TOO_LARGE" in diagnostic_codes(
        lint(enormous_ref, "numeric")
    )

    cp_online = """参考文献
[1] Zotero.[Zotero download][CP/OL].https://example.org/download.
"""
    assert "ACCESS_DATE_CONTEXT" in diagnostic_codes(lint(cp_online, "numeric"))
    assert "ACCESS_DATE_MISSING" in diagnostic_codes(
        lint(cp_online, "numeric", web_context=True)
    )

    cd_without_path = """参考文献
[1] 示例程序[CP/CD].
"""
    assert "ELECTRONIC_PATH_UNRECOGNIZED" in diagnostic_codes(
        lint(cd_without_path, "numeric")
    )
    print("self-test: ok")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="对 GB/T 7714—2025 文本做保守结构预检（不自动改写）"
    )
    parser.add_argument("input", nargs="?", help="UTF-8 文本文件；使用 - 从标准输入读取")
    parser.add_argument(
        "--system",
        choices=("auto", "numeric", "author-date"),
        default="auto",
        help="目标标引体系（默认自动识别）",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="输出格式",
    )
    parser.add_argument(
        "--standardization-document",
        action="store_true",
        help="确认宿主是标准化文件；其中标准条目可省略 [S]",
    )
    parser.add_argument(
        "--web-context",
        action="store_true",
        help="确认待审条目采用第 8.11 条网站/网页模板",
    )
    parser.add_argument("--strict", action="store_true", help="警告也返回非零状态")
    parser.add_argument("--self-test", action="store_true", help="运行内置回归测试")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.self_test:
        run_self_test()
        return 0
    if not args.input:
        raise SystemExit("必须提供 input，或使用 --self-test")

    result = lint(
        read_input(args.input),
        args.system,
        standardization_document=args.standardization_document,
        web_context=args.web_context,
    )
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_text(result))
    if result["errors"] or (args.strict and result["warnings"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
