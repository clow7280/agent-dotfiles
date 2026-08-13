#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = ["requests>=2.32.4,<3"]
# ///
"""使用 MinerU 精准解析 API 将 PDF 交付为 Markdown ZIP 包。"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.parse
import zipfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

import requests

API_BASE = "https://mineru.net"
TERMINAL_STATES = {"done", "failed"}
ACTIVE_STATES = {"waiting-file", "pending", "running", "converting"}

# API 参考 references/mineru-precise-api.md 第 126-128 行：
# -60007 模型服务暂时不可用、-60009 任务队列已满、-10001 服务异常，可稍后重试。
RETRYABLE_CODES: set[int | str] = {-60007, -60009, -10001}
MAX_RETRIES = 3
RETRY_BASE_DELAY = 5  # 秒，实际延迟为 base * 2^attempt
MARKDOWN_IMAGE_RE = re.compile(
    r"(?P<prefix>!\[[^\]\n]*\]\()(?P<target><[^>\n]+>|[^\s)]+)(?P<suffix>[^)\n]*\))"
)
HTML_IMAGE_RE = re.compile(
    r"(?P<prefix><img\b[^>]*?\bsrc\s*=\s*)(?P<quote>['\"])(?P<target>.*?)(?P=quote)",
    re.IGNORECASE,
)


class MinerUError(RuntimeError):
    """表示输入、API 或交付物不符合契约。

    retryable 为 True 时表示瞬时故障，调用方可按有限次数重试。
    """

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


def eprint(*args: object) -> None:
    print(*args, file=sys.stderr)


def is_retryable_status(status_code: int) -> bool:
    """HTTP 429 与 5xx 视为可重试的瞬时故障。"""
    return status_code == 429 or status_code >= 500


def with_retry[T](operation: Callable[[], T], label: str) -> T:
    """以指数退避重试 operation，最多重试 MAX_RETRIES 次。

    仅当 MinerUError 标记为 retryable 时重试，其余错误直接抛出。
    """
    last_error: MinerUError | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            return operation()
        except MinerUError as exc:
            last_error = exc
            if not exc.retryable or attempt >= MAX_RETRIES:
                raise
            delay = RETRY_BASE_DELAY * (2**attempt)
            eprint(f"{label}（{exc}），{delay} 秒后重试（第 {attempt + 1}/{MAX_RETRIES} 次）")
            time.sleep(delay)
    raise last_error  # 不应到达此处，仅为类型安全


def get_token() -> str:
    token = os.environ.get("MINERU_API_KEY") or os.environ.get("MINERU_TOKEN")
    if not token or not token.strip():
        raise MinerUError(
            "未找到 MINERU_API_KEY 或 MINERU_TOKEN。请在本机环境变量中设置 MinerU token。"
        )
    return token.strip()


def auth_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "*/*",
        "Content-Type": "application/json",
    }


def safe_text(text: str, limit: int = 500) -> str:
    redacted = re.sub(r"Bearer\s+[A-Za-z0-9._\-]+", "Bearer ***", text)
    redacted = re.sub(
        r"([?&](?:Signature|Expires|OSSAccessKeyId|x-oss-[^=]+)=)[^&\s\"']+",
        r"\1***",
        redacted,
        flags=re.IGNORECASE,
    )
    return redacted[:limit]


def _extract_code(result: dict[str, Any]) -> int | str:
    """从响应 JSON 提取业务错误码，优先使用 code，回退到 msgCode。"""
    raw = result.get("code", result.get("msgCode", "unknown"))
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        try:
            return int(raw)
        except ValueError:
            return raw
    return "unknown"


def _http_json_once(
    method: str,
    url: str,
    token: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: int = 60,
) -> dict[str, Any]:
    """执行单次 HTTP 请求并解析 JSON 响应。"""
    try:
        response = requests.request(
            method,
            url,
            headers=auth_headers(token),
            json=payload,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise MinerUError(f"网络请求失败: {exc}", retryable=True) from exc

    try:
        result = response.json()
    except requests.JSONDecodeError as exc:
        raise MinerUError(
            f"HTTP {response.status_code} 返回的内容不是 JSON: {safe_text(response.text)}",
            retryable=is_retryable_status(response.status_code),
        ) from exc

    if not response.ok:
        code = _extract_code(result)
        message = result.get("msg", result.get("message", response.reason))
        retryable = code in RETRYABLE_CODES or is_retryable_status(response.status_code)
        raise MinerUError(
            f"HTTP {response.status_code} 调用失败: code={code} msg={message}",
            retryable=retryable,
        )

    # 兼容两种响应外壳：文档版 code==0 和部署版 success==True。
    # 当两个标志字段均缺失时（即响应仅有 data），视为成功以容忍未来的格式变更。
    documented_success = result.get("code") == 0
    deployed_success = result.get("success") is True
    has_neither_flag = "code" not in result and "success" not in result
    if not (documented_success or deployed_success or has_neither_flag):
        code = _extract_code(result)
        message = result.get("msg", result.get("message", "未知错误"))
        raise MinerUError(
            f"MinerU 返回错误: code={code} msg={message}",
            retryable=code in RETRYABLE_CODES,
        )
    if not isinstance(result.get("data"), dict):
        raise MinerUError("MinerU 成功响应缺少 data 对象。")
    return result


def http_json(
    method: str,
    url: str,
    token: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: int = 60,
) -> dict[str, Any]:
    """带有限重试的 HTTP JSON 请求。

    对网络错误、HTTP 429/5xx 和 RETRYABLE_CODES 中的业务错误码自动重试，
    使用指数退避策略（base * 2^attempt 秒）。
    """
    return with_retry(
        lambda: _http_json_once(method, url, token, payload, timeout=timeout),
        "请求失败",
    )


def put_file(upload_url: str, path: Path) -> None:
    """PUT 上传文件，对网络错误与 HTTP 429/5xx 做有限重试。"""

    def attempt_upload() -> None:
        try:
            with path.open("rb") as file_handle:
                response = requests.put(upload_url, data=file_handle, timeout=300)
        except (OSError, requests.RequestException) as exc:
            raise MinerUError(f"上传失败 {path.name}: {exc}", retryable=True) from exc
        if response.status_code in {200, 201, 204}:
            return
        raise MinerUError(
            f"上传失败 {path.name}: HTTP {response.status_code} {safe_text(response.text)}",
            retryable=is_retryable_status(response.status_code),
        )

    with_retry(attempt_upload, "上传失败")


def download_file(url: str, destination: Path) -> None:
    """下载文件，对网络错误与 HTTP 429/5xx 做有限重试。"""

    def attempt_download() -> None:
        try:
            with requests.get(url, stream=True, timeout=300) as response:
                if response.status_code != 200:
                    raise MinerUError(
                        f"下载解析结果失败: HTTP {response.status_code} "
                        f"{safe_text(response.text)}",
                        retryable=is_retryable_status(response.status_code),
                    )
                with destination.open("wb") as file_handle:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            file_handle.write(chunk)
        except requests.RequestException as exc:
            raise MinerUError(f"下载解析结果失败: {exc}", retryable=True) from exc

    with_retry(attempt_download, "下载失败")


def output_stem(source: str) -> str:
    path = urllib.parse.urlparse(source).path
    stem = Path(urllib.parse.unquote(path)).stem or Path(source).stem
    stem = re.sub(r"[\x00-\x1f/\\:]+", "_", stem).strip(" ._")
    return stem[:120] or "document"


def data_id(source: str, index: int) -> str:
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]
    return f"pdf-{index}-{digest}"


def discover_pdfs(inputs: list[str]) -> list[Path]:
    pdfs: list[Path] = []
    for item in inputs:
        path = Path(item).expanduser()
        if path.is_dir():
            # rglob 的通配在 POSIX 下大小写敏感，改用后缀过滤以兼容 .PDF 等写法
            pdfs.extend(
                sorted(
                    p
                    for p in path.rglob("*")
                    if p.is_file() and p.suffix.lower() == ".pdf"
                )
            )
        elif path.is_file() and path.suffix.lower() == ".pdf":
            pdfs.append(path)
        else:
            raise MinerUError(f"输入不是 PDF 文件或包含 PDF 的目录: {item}")

    unique: list[Path] = []
    seen: set[Path] = set()
    for pdf in pdfs:
        resolved = pdf.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    if inputs and not unique:
        raise MinerUError("输入目录中没有找到 PDF 文件。")
    return unique


def validate_pdf_urls(urls: list[str]) -> list[str]:
    validated: list[str] = []
    for url in urls:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise MinerUError(f"PDF URL 必须使用 HTTP 或 HTTPS: {url}")
        if not parsed.path.lower().endswith(".pdf"):
            eprint(f"警告: URL 路径未以 .pdf 结尾，MinerU 可能无法识别文件类型: {url}")
        validated.append(url)
    return validated


def chunks(items: list[Any], size: int) -> list[list[Any]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def build_common_payload(args: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model_version": args.model_version,
        "enable_formula": not args.no_formula,
        "enable_table": not args.no_table,
    }
    if args.language:
        payload["language"] = args.language
    return payload


def submit_local_batch(
    paths: list[Path],
    args: argparse.Namespace,
    token: str,
    start_index: int,
) -> tuple[str, dict[str, str]]:
    files: list[dict[str, Any]] = []
    names: dict[str, str] = {}
    for offset, path in enumerate(paths):
        identifier = data_id(str(path), start_index + offset)
        entry: dict[str, Any] = {"name": path.name, "data_id": identifier}
        if args.ocr:
            entry["is_ocr"] = True
        if args.page_ranges:
            entry["page_ranges"] = args.page_ranges
        files.append(entry)
        names[identifier] = output_stem(path.name)

    payload = build_common_payload(args)
    payload["files"] = files
    result = http_json("POST", f"{API_BASE}/api/v4/file-urls/batch", token, payload)
    response_data = result["data"]
    batch_id = response_data.get("batch_id")
    upload_urls = response_data.get("file_urls")
    if not isinstance(batch_id, str) or not batch_id:
        raise MinerUError("MinerU 响应缺少 batch_id。")
    if not isinstance(upload_urls, list) or len(upload_urls) != len(paths):
        raise MinerUError("MinerU 返回的上传 URL 数量与文件数量不一致。")

    for path, upload_url in zip(paths, upload_urls, strict=True):
        if not isinstance(upload_url, str) or not upload_url:
            raise MinerUError("MinerU 返回了无效的文件上传 URL。")
        eprint(f"上传: {path}")
        put_file(upload_url, path)
    return batch_id, names


def submit_url_batch(
    urls: list[str],
    args: argparse.Namespace,
    token: str,
    start_index: int,
) -> tuple[str, dict[str, str]]:
    files: list[dict[str, Any]] = []
    names: dict[str, str] = {}
    for offset, url in enumerate(urls):
        identifier = data_id(url, start_index + offset)
        entry: dict[str, Any] = {"url": url, "data_id": identifier}
        if args.ocr:
            entry["is_ocr"] = True
        if args.page_ranges:
            entry["page_ranges"] = args.page_ranges
        files.append(entry)
        names[identifier] = output_stem(url)

    payload = build_common_payload(args)
    payload["files"] = files
    if args.no_cache:
        payload["no_cache"] = True
    if args.cache_tolerance is not None:
        payload["cache_tolerance"] = args.cache_tolerance
    result = http_json("POST", f"{API_BASE}/api/v4/extract/task/batch", token, payload)
    batch_id = result["data"].get("batch_id")
    if not isinstance(batch_id, str) or not batch_id:
        raise MinerUError("MinerU 响应缺少 batch_id。")
    return batch_id, names


def poll_batch(batch_id: str, token: str, interval: int, timeout: int) -> list[dict[str, Any]]:
    deadline = time.monotonic() + timeout
    last_summary = ""
    last_unknown: tuple[str, ...] = ()
    current_interval = interval
    max_interval = max(interval * 6, 120)  # 上限取 6 倍初始间隔与 120 秒中的较大者
    while True:
        result = http_json(
            "GET", f"{API_BASE}/api/v4/extract-results/batch/{batch_id}", token
        )
        items = result["data"].get("extract_result", [])
        if not isinstance(items, list):
            raise MinerUError("MinerU 批量结果中的 extract_result 不是数组。")

        counts: dict[str, int] = {}
        for item in items:
            state = str(item.get("state", "unknown"))
            counts[state] = counts.get(state, 0) + 1
        summary = ", ".join(f"{state}={count}" for state, count in sorted(counts.items()))
        if summary != last_summary:
            eprint(f"批次 {batch_id}: {summary or '等待结果'}")
            last_summary = summary

        states = {item.get("state") for item in items}
        if items and states.issubset(TERMINAL_STATES):
            return items
        unknown = states - TERMINAL_STATES - ACTIVE_STATES
        unknown_labels = tuple(sorted(str(state) for state in unknown))
        if unknown_labels and unknown_labels != last_unknown:
            eprint(f"警告: MinerU 返回未知任务状态 {list(unknown_labels)}")
            last_unknown = unknown_labels
        if time.monotonic() >= deadline:
            raise MinerUError(f"轮询超时: batch_id={batch_id}")
        time.sleep(current_interval)
        # 指数退避：每轮增加 50%，直到上限
        current_interval = min(int(current_interval * 1.5), max_interval)


def safe_extract(zip_path: Path, destination: Path) -> None:
    destination_resolved = destination.resolve()
    try:
        with zipfile.ZipFile(zip_path) as archive:
            for member in archive.infolist():
                target = (destination / member.filename).resolve()
                if not target.is_relative_to(destination_resolved):
                    raise MinerUError(f"MinerU ZIP 包含非法路径: {member.filename}")
            archive.extractall(destination)
    except zipfile.BadZipFile as exc:
        raise MinerUError("MinerU 返回的解析结果不是有效 ZIP 文件。") from exc


def find_full_markdown(extracted: Path) -> Path:
    candidates = sorted(
        (path for path in extracted.rglob("full.md") if path.is_file()),
        key=lambda path: (len(path.relative_to(extracted).parts), str(path)),
    )
    if not candidates:
        raise MinerUError("MinerU ZIP 中没有找到 full.md。")
    return candidates[0]


def split_local_target(raw_target: str) -> tuple[str, bool]:
    angled = raw_target.startswith("<") and raw_target.endswith(">")
    target = raw_target[1:-1] if angled else raw_target
    parsed = urllib.parse.urlsplit(target)
    if parsed.scheme or parsed.netloc or target.startswith("data:"):
        return target, False
    return urllib.parse.unquote(parsed.path), True


def rewrite_images(markdown: str, markdown_path: Path, staging: Path) -> tuple[str, int]:
    figures = staging / "figs"
    copied: dict[Path, str] = {}
    used_names: dict[str, Path] = {}
    extraction_root = markdown_path.parent.resolve()

    def local_destination(raw_target: str) -> str:
        local_path, is_local = split_local_target(raw_target)
        if not is_local:
            return raw_target
        if not local_path or local_path.startswith("/"):
            raise MinerUError(f"Markdown 包含无效的本地图片引用: {raw_target}")

        source = (markdown_path.parent / local_path).resolve()
        if not source.is_relative_to(extraction_root):
            raise MinerUError(f"Markdown 图片引用越出解析结果目录: {raw_target}")
        if not source.is_file():
            raise MinerUError(f"Markdown 图片引用不存在: {raw_target}")
        if source in copied:
            return copied[source]

        # 空白与括号会破坏 Markdown 图片语法，复制进 figs/ 时净化文件名
        filename = re.sub(r"[\s()]+", "_", source.name)
        existing = used_names.get(filename)
        if existing is not None and existing != source:
            prefix = hashlib.sha256(str(source).encode("utf-8")).hexdigest()[:8]
            filename = f"{prefix}-{filename}"
        used_names[filename] = source
        figures.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, figures / filename)
        destination = PurePosixPath("figs", filename).as_posix()
        copied[source] = destination
        return destination

    def replace_markdown(match: re.Match[str]) -> str:
        raw_target = match.group("target")
        replacement = local_destination(raw_target)
        return f"{match.group('prefix')}{replacement}{match.group('suffix')}"

    def replace_html(match: re.Match[str]) -> str:
        raw_target = match.group("target")
        replacement = local_destination(raw_target)
        quote = match.group("quote")
        return f"{match.group('prefix')}{quote}{replacement}{quote}"

    rewritten = MARKDOWN_IMAGE_RE.sub(replace_markdown, markdown)
    rewritten = HTML_IMAGE_RE.sub(replace_html, rewritten)
    return rewritten, len(copied)


def build_delivery(raw_zip: Path, destination_zip: Path, stem: str) -> tuple[int, int]:
    with tempfile.TemporaryDirectory(prefix="mineru-delivery-") as temporary:
        work = Path(temporary)
        extracted = work / "extracted"
        staging = work / "delivery"
        extracted.mkdir()
        staging.mkdir()
        safe_extract(raw_zip, extracted)

        full_markdown = find_full_markdown(extracted)
        markdown = full_markdown.read_text(encoding="utf-8", errors="strict")
        if not markdown.strip():
            raise MinerUError("MinerU 返回的 full.md 为空。")
        rewritten, figure_count = rewrite_images(markdown, full_markdown, staging)
        markdown_name = f"{stem}.md"
        (staging / markdown_name).write_text(rewritten, encoding="utf-8")

        archive_path = work / f"{stem}.zip"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(staging / markdown_name, markdown_name)
            figures = staging / "figs"
            if figures.exists():
                for figure in sorted(path for path in figures.rglob("*") if path.is_file()):
                    archive.write(figure, figure.relative_to(staging).as_posix())

        destination_zip.parent.mkdir(parents=True, exist_ok=True)
        # shutil.move 兼容输出目录与系统临时目录跨设备的情况
        shutil.move(archive_path, destination_zip)
        character_count = len(rewritten.replace("\r", "").replace("\n", ""))
        return character_count, figure_count


def unique_destination(out_root: Path, stem: str, reserved: set[Path]) -> Path:
    candidate = out_root / f"{stem}.zip"
    suffix = 2
    while candidate in reserved:
        candidate = out_root / f"{stem}-{suffix}.zip"
        suffix += 1
    reserved.add(candidate)
    return candidate


def materialize_results(
    results: list[dict[str, Any]],
    out_root: Path,
    names: dict[str, str],
    reserved: set[Path],
    successes: list[str],
) -> list[str]:
    failures: list[str] = []
    for item in results:
        identifier = item.get("data_id")
        file_name = str(item.get("file_name") or identifier or "document")
        state = item.get("state")
        if state != "done":
            message = str(item.get("err_msg") or "未知错误")
            failures.append(f"{file_name}: state={state} msg={message}")
            continue

        zip_url = item.get("full_zip_url")
        if not isinstance(zip_url, str) or not zip_url:
            failures.append(f"{file_name}: done 状态缺少 full_zip_url")
            continue

        stem = names.get(str(identifier)) or output_stem(file_name)
        destination = unique_destination(out_root, stem, reserved)
        with tempfile.TemporaryDirectory(prefix="mineru-result-") as temporary:
            raw_zip = Path(temporary) / "result.zip"
            eprint(f"下载并打包: {file_name}")
            download_file(zip_url, raw_zip)
            character_count, figure_count = build_delivery(raw_zip, destination, destination.stem)
        eprint(
            f"完成: {destination}，Markdown 字符数 {character_count}，插图 {figure_count} 张"
        )
        successes.append(str(destination))
    return failures


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="使用 MinerU 精准解析 API 将 PDF 解析并打包为 Markdown ZIP。"
    )
    parser.add_argument("inputs", nargs="*", help="PDF 文件或包含 PDF 的目录。")
    parser.add_argument("--url", action="append", default=[], help="PDF URL，可重复传入。")
    parser.add_argument("--out", default="parsed", help="ZIP 输出目录，默认 parsed。")
    parser.add_argument(
        "--model-version",
        default="vlm",
        choices=["pipeline", "vlm"],
        help="MinerU 模型版本，默认 vlm。",
    )
    parser.add_argument(
        "--language",
        help="外部探查后确定的主要语言代码；不传时使用 MinerU 默认值 ch。",
    )
    parser.add_argument(
        "--ocr",
        action="store_true",
        help="启用 OCR；必须先在脚本外探查 PDF，且同时显式传入 --language。",
    )
    parser.add_argument("--no-formula", action="store_true", help="关闭公式识别。")
    parser.add_argument("--no-table", action="store_true", help="关闭表格识别。")
    parser.add_argument("--page-ranges", help='页码范围，例如 "2,4-6"。')
    parser.add_argument("--batch-size", type=int, default=50, help="批大小，最大 50。")
    parser.add_argument("--poll-interval", type=int, default=10, help="轮询间隔秒数。")
    parser.add_argument("--timeout", type=int, default=3600, help="单批次轮询超时秒数。")
    parser.add_argument("--no-cache", action="store_true", help="URL 解析时绕过 MinerU 缓存。")
    parser.add_argument("--cache-tolerance", type=int, help="URL 缓存容忍秒数。")
    return parser.parse_args(argv)


def validate_args(args: argparse.Namespace) -> None:
    if not args.inputs and not args.url:
        raise MinerUError("请提供 PDF 文件、PDF 目录或 --url。")
    if not 1 <= args.batch_size <= 50:
        raise MinerUError("--batch-size 必须在 1 到 50 之间。")
    if args.poll_interval < 1:
        raise MinerUError("--poll-interval 必须大于 0。")
    if args.timeout < 1:
        raise MinerUError("--timeout 必须大于 0。")
    if args.cache_tolerance is not None and args.cache_tolerance < 0:
        raise MinerUError("--cache-tolerance 不能小于 0。")
    if args.ocr and not args.language:
        raise MinerUError("启用 --ocr 前必须外部探查主要语言，并显式传入 --language。")


def process_batches(
    groups: list[list[Any]],
    submit: Callable[[list[Any], argparse.Namespace, str, int], tuple[str, dict[str, str]]],
    args: argparse.Namespace,
    token: str,
    out_root: Path,
    reserved: set[Path],
    label: str,
    successes: list[str],
) -> list[str]:
    failures: list[str] = []
    start_index = 0
    for group in groups:
        eprint(f"提交{label}批次: {len(group)} 个 PDF")
        batch_id, names = submit(group, args, token, start_index)
        results = poll_batch(batch_id, token, args.poll_interval, args.timeout)
        failures.extend(materialize_results(results, out_root, names, reserved, successes))
        start_index += len(group)
    return failures


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    validate_args(args)
    pdfs = discover_pdfs(args.inputs) if args.inputs else []
    urls = validate_pdf_urls(args.url)
    token = get_token()
    out_root = Path(args.out).expanduser().resolve()
    reserved: set[Path] = set()
    successes: list[str] = []

    failures = process_batches(
        chunks(pdfs, args.batch_size),
        submit_local_batch,
        args,
        token,
        out_root,
        reserved,
        "本地文件",
        successes,
    )
    failures.extend(
        process_batches(
            chunks(urls, args.batch_size),
            submit_url_batch,
            args,
            token,
            out_root,
            reserved,
            "URL",
            successes,
        )
    )
    if failures:
        if successes:
            success_list = "\n".join(f"  ✓ {path}" for path in successes)
            eprint(f"已成功交付 {len(successes)} 个文件:\n{success_list}")
        details = "\n".join(f"- {failure}" for failure in failures)
        raise MinerUError(f"部分 PDF 解析失败:\n{details}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except MinerUError as exc:
        eprint(f"错误: {exc}")
        raise SystemExit(1)
