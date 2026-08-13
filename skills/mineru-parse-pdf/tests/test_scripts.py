from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import ModuleType
from typing import Self
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str, relative_path: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 {relative_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


mineru_parse = load_script("mineru_parse_test", "scripts/mineru_parse.py")
markdown_quality = load_script("markdown_quality_test", "scripts/markdown_quality.py")


class FakeResponse:
    def __init__(self, payload: dict[str, object], *, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code
        self.ok = 200 <= status_code < 400
        self.reason = "test"
        self.text = "test"

    def json(self) -> dict[str, object]:
        return self.payload

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def iter_content(self, chunk_size: int) -> list[bytes]:
        return [b"data"]


class HttpJsonTests(unittest.TestCase):
    def test_accepts_documented_success_shape(self) -> None:
        response = FakeResponse({"code": 0, "msg": "ok", "data": {"batch_id": "batch"}})
        with mock.patch.object(mineru_parse.requests, "request", return_value=response):
            result = mineru_parse.http_json("POST", "https://example.test", "secret", {})
        self.assertEqual(result["data"]["batch_id"], "batch")

    def test_reports_deployed_error_shape(self) -> None:
        response = FakeResponse(
            {
                "success": False,
                "msgCode": "A0202",
                "msg": "user authenticate failed",
                "data": None,
            }
        )
        with (
            mock.patch.object(mineru_parse.requests, "request", return_value=response),
            self.assertRaisesRegex(mineru_parse.MinerUError, "A0202"),
        ):
            mineru_parse.http_json("POST", "https://example.test", "secret", {})

    def test_accepts_response_without_code_or_success(self) -> None:
        """当 code 和 success 字段均缺失但 data 存在时，应视为成功。"""
        response = FakeResponse({"data": {"batch_id": "batch"}})
        with mock.patch.object(mineru_parse.requests, "request", return_value=response):
            result = mineru_parse.http_json("POST", "https://example.test", "secret", {})
        self.assertEqual(result["data"]["batch_id"], "batch")

    def test_retries_on_retryable_code(self) -> None:
        """对 RETRYABLE_CODES 中的错误码应自动重试。"""
        fail_response = FakeResponse(
            {"code": -60007, "msg": "模型服务暂时不可用", "data": {}}
        )
        ok_response = FakeResponse(
            {"code": 0, "msg": "ok", "data": {"batch_id": "batch"}}
        )
        with (
            mock.patch.object(
                mineru_parse.requests,
                "request",
                side_effect=[fail_response, ok_response],
            ),
            mock.patch.object(mineru_parse.time, "sleep"),
        ):
            result = mineru_parse.http_json("POST", "https://example.test", "secret", {})
        self.assertEqual(result["data"]["batch_id"], "batch")

    def test_retries_on_network_error(self) -> None:
        """网络级别错误应自动重试。"""
        ok_response = FakeResponse(
            {"code": 0, "msg": "ok", "data": {"batch_id": "batch"}}
        )
        with (
            mock.patch.object(
                mineru_parse.requests,
                "request",
                side_effect=[
                    mineru_parse.requests.ConnectionError("connection reset"),
                    ok_response,
                ],
            ),
            mock.patch.object(mineru_parse.time, "sleep"),
        ):
            result = mineru_parse.http_json("POST", "https://example.test", "secret", {})
        self.assertEqual(result["data"]["batch_id"], "batch")

    def test_retries_on_server_error_status(self) -> None:
        """HTTP 5xx 应自动重试。"""
        fail_response = FakeResponse(
            {"code": "unknown", "msg": "bad gateway", "data": {}},
            status_code=502,
        )
        ok_response = FakeResponse(
            {"code": 0, "msg": "ok", "data": {"batch_id": "batch"}}
        )
        with (
            mock.patch.object(
                mineru_parse.requests,
                "request",
                side_effect=[fail_response, ok_response],
            ),
            mock.patch.object(mineru_parse.time, "sleep"),
        ):
            result = mineru_parse.http_json("POST", "https://example.test", "secret", {})
        self.assertEqual(result["data"]["batch_id"], "batch")

    def test_no_retry_on_client_error_status(self) -> None:
        """HTTP 4xx 参数错误不应重试。"""
        fail_response = FakeResponse(
            {"code": -10002, "msg": "参数错误", "data": {}}, status_code=400
        )
        with (
            mock.patch.object(
                mineru_parse.requests,
                "request",
                return_value=fail_response,
            ) as mock_request,
            self.assertRaisesRegex(mineru_parse.MinerUError, "-10002"),
        ):
            mineru_parse.http_json("POST", "https://example.test", "secret", {})
        self.assertEqual(mock_request.call_count, 1)

    def test_no_retry_on_auth_error(self) -> None:
        """鉴权错误不应重试。"""
        fail_response = FakeResponse(
            {
                "success": False,
                "msgCode": "A0202",
                "msg": "user authenticate failed",
                "data": None,
            }
        )
        with (
            mock.patch.object(
                mineru_parse.requests,
                "request",
                return_value=fail_response,
            ) as mock_request,
            self.assertRaisesRegex(mineru_parse.MinerUError, "A0202"),
        ):
            mineru_parse.http_json("POST", "https://example.test", "secret", {})
        # 应只调用一次，不重试
        self.assertEqual(mock_request.call_count, 1)

    def test_retry_exhaustion_raises(self) -> None:
        """重试次数耗尽后应抛出最后一次的错误。"""
        fail_response = FakeResponse(
            {"code": -60009, "msg": "任务队列已满", "data": {}}
        )
        with (
            mock.patch.object(
                mineru_parse.requests,
                "request",
                return_value=fail_response,
            ),
            mock.patch.object(mineru_parse.time, "sleep"),
            self.assertRaisesRegex(mineru_parse.MinerUError, "-60009"),
        ):
            mineru_parse.http_json("POST", "https://example.test", "secret", {})


class DeliveryTests(unittest.TestCase):
    def test_builds_markdown_and_figs_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw_zip = root / "raw.zip"
            with zipfile.ZipFile(raw_zip, "w") as archive:
                archive.writestr("result/full.md", "# 标题\n\n![图](images/a.png)\n")
                archive.writestr("result/images/a.png", b"png")
                archive.writestr("result/model.json", "{}")

            destination = root / "paper.zip"
            character_count, figure_count = mineru_parse.build_delivery(
                raw_zip, destination, "paper"
            )

            self.assertGreater(character_count, 0)
            self.assertEqual(figure_count, 1)
            with zipfile.ZipFile(destination) as archive:
                self.assertEqual(sorted(archive.namelist()), ["figs/a.png", "paper.md"])
                markdown = archive.read("paper.md").decode("utf-8")
            self.assertIn("](figs/a.png)", markdown)

            report = markdown_quality.inspect_zip(destination)
            self.assertEqual(report["local_image_count"], 1)
            self.assertEqual(report["missing_image_refs"], [])
            self.assertEqual(report["unexpected_files"], [])

    def test_rejects_missing_image(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw_zip = root / "raw.zip"
            with zipfile.ZipFile(raw_zip, "w") as archive:
                archive.writestr("full.md", "![缺失](images/missing.png)\n")
            with self.assertRaisesRegex(mineru_parse.MinerUError, "不存在"):
                mineru_parse.build_delivery(raw_zip, root / "paper.zip", "paper")

    def test_rejects_zip_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw_zip = root / "raw.zip"
            with zipfile.ZipFile(raw_zip, "w") as archive:
                archive.writestr("../outside.txt", "unsafe")
            with self.assertRaisesRegex(mineru_parse.MinerUError, "非法路径"):
                mineru_parse.safe_extract(raw_zip, root / "extract")

    def test_sanitizes_image_filename_for_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw_zip = root / "raw.zip"
            with zipfile.ZipFile(raw_zip, "w") as archive:
                archive.writestr(
                    "full.md", "![图](<images/my fig(1).png>)\n"
                )
                archive.writestr("images/my fig(1).png", b"png")

            destination = root / "paper.zip"
            _, figure_count = mineru_parse.build_delivery(
                raw_zip, destination, "paper"
            )

            self.assertEqual(figure_count, 1)
            with zipfile.ZipFile(destination) as archive:
                self.assertEqual(
                    sorted(archive.namelist()),
                    ["figs/my_fig_1_.png", "paper.md"],
                )
                markdown = archive.read("paper.md").decode("utf-8")
            self.assertIn("](figs/my_fig_1_.png)", markdown)

            report = markdown_quality.inspect_zip(destination)
            self.assertEqual(report["missing_image_refs"], [])


class FileTransferTests(unittest.TestCase):
    def test_upload_retries_on_network_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "paper.pdf"
            path.write_bytes(b"pdf")
            with (
                mock.patch.object(
                    mineru_parse.requests,
                    "put",
                    side_effect=[
                        mineru_parse.requests.ConnectionError("connection reset"),
                        FakeResponse({}, status_code=200),
                    ],
                ) as mock_put,
                mock.patch.object(mineru_parse.time, "sleep"),
            ):
                mineru_parse.put_file("https://upload.test", path)
            self.assertEqual(mock_put.call_count, 2)

    def test_download_retries_on_server_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "result.zip"
            with (
                mock.patch.object(
                    mineru_parse.requests,
                    "get",
                    side_effect=[
                        FakeResponse({}, status_code=503),
                        FakeResponse({}, status_code=200),
                    ],
                ) as mock_get,
                mock.patch.object(mineru_parse.time, "sleep"),
            ):
                mineru_parse.download_file("https://download.test", destination)
            self.assertEqual(mock_get.call_count, 2)
            self.assertEqual(destination.read_bytes(), b"data")


class ArgumentTests(unittest.TestCase):
    def test_ocr_requires_explicit_language(self) -> None:
        args = mineru_parse.parse_args(["paper.pdf", "--ocr"])
        with self.assertRaisesRegex(mineru_parse.MinerUError, "--language"):
            mineru_parse.validate_args(args)

    def test_url_without_pdf_suffix_warns_not_rejects(self) -> None:
        """无 .pdf 后缀的 URL 应返回结果而非抛出异常。"""
        urls = mineru_parse.validate_pdf_urls(["https://arxiv.org/pdf/2301.00001"])
        self.assertEqual(len(urls), 1)
        self.assertEqual(urls[0], "https://arxiv.org/pdf/2301.00001")

    def test_url_with_pdf_suffix_accepted(self) -> None:
        """正常 .pdf 后缀的 URL 应正常通过。"""
        urls = mineru_parse.validate_pdf_urls(["https://example.com/paper.pdf"])
        self.assertEqual(len(urls), 1)

    def test_url_with_invalid_scheme_rejected(self) -> None:
        """非 HTTP/HTTPS 的 URL 应被拒绝。"""
        with self.assertRaisesRegex(mineru_parse.MinerUError, "HTTP"):
            mineru_parse.validate_pdf_urls(["ftp://example.com/paper.pdf"])

    def test_discovers_uppercase_pdf_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "PAPER.PDF").write_bytes(b"pdf")
            (root / "note.txt").write_text("text", encoding="utf-8")

            pdfs = mineru_parse.discover_pdfs([str(root)])

            self.assertEqual([path.name for path in pdfs], ["PAPER.PDF"])


if __name__ == "__main__":
    unittest.main()
