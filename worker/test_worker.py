"""Tests for worker.py — the monolithic worker module.

Covers all extractors, routing, activities, workflow, and run_worker.
Libraries like docx, pymupdf, openpyxl, pytesseract, PIL are imported
locally inside functions, so we mock them via sys.modules injection.
"""

import asyncio
import csv
import io
import os
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

os.environ.setdefault("ELASTICSEARCH_URL", "http://localhost:9200")
os.environ.setdefault("BACKEND_URL", "http://localhost:8080")
os.environ.setdefault("TEMPORAL_HOST", "localhost:7233")

import worker
from worker import (
    DocumentTask,
    ExtractionResult,
    IndexResult,
    _extract_plaintext,
    _extract_html,
    _extract_csv,
    _extract_docx,
    _extract_pdf,
    _extract_xlsx,
    _extract_image_ocr,
    _ocr_bytes,
    _do_extract,
    DocumentProcessingWorkflow,
)


# ═══════════════════════════════════════════════════════════════
# Extractor helpers
# ═══════════════════════════════════════════════════════════════


class TestExtractPlaintext:

    def test_reads_utf8(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("Hello UTF-8 world", encoding="utf-8")
        assert _extract_plaintext(f) == "Hello UTF-8 world"

    def test_reads_latin1_fallback(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_bytes(b"caf\xe9 latte")
        result = _extract_plaintext(f)
        assert "caf" in result and "latte" in result

    def test_reads_simple_ascii(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_bytes(b"simple ascii")
        assert _extract_plaintext(f) == "simple ascii"


class TestExtractHtml:

    def test_strips_tags_with_bs4(self, tmp_html_file):
        result = _extract_html(tmp_html_file)
        assert "Title" in result
        assert "Content here" in result
        assert "alert" not in result
        assert "body{}" not in result

    def test_regex_fallback_when_no_bs4(self, tmp_path):
        """Directly test the regex fallback by simulating ImportError for bs4."""
        import re

        f = tmp_path / "page.html"
        f.write_text("<h1>Hello</h1><p>World</p>")

        # Make bs4 import fail temporarily
        real_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

        def fake_import(name, *args, **kwargs):
            if name == "bs4":
                raise ImportError("no bs4")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            result = _extract_html(f)

        assert "Hello" in result
        assert "World" in result


class TestExtractCsv:

    def test_csv_extraction(self, tmp_csv_file):
        result = _extract_csv(tmp_csv_file)
        assert "Columns: name | age | city" in result
        assert "Alice | 30 | NYC" in result
        assert "Bob | 25 | LA" in result

    def test_tsv_extraction(self, tmp_tsv_file):
        result = _extract_csv(tmp_tsv_file, delimiter="\t")
        assert "Columns: name | age | city" in result
        assert "Alice | 30 | NYC" in result

    def test_large_csv_truncates(self, tmp_path):
        f = tmp_path / "big.csv"
        with open(f, "w", newline="") as fp:
            w = csv.writer(fp)
            w.writerow(["col1", "col2"])
            for i in range(600):
                w.writerow([f"val{i}", f"data{i}"])
        result = _extract_csv(f)
        assert "rows total" in result


class TestExtractDocx:

    def test_with_python_docx(self, tmp_path):
        mock_para1 = MagicMock()
        mock_para1.text = "Paragraph one"
        mock_para2 = MagicMock()
        mock_para2.text = "Paragraph two"
        mock_para_empty = MagicMock()
        mock_para_empty.text = "   "

        mock_doc_obj = MagicMock()
        mock_doc_obj.paragraphs = [mock_para1, mock_para_empty, mock_para2]
        mock_doc_obj.tables = []

        mock_docx = MagicMock()
        mock_docx.Document.return_value = mock_doc_obj

        with patch.dict("sys.modules", {"docx": mock_docx}):
            result = _extract_docx(tmp_path / "test.docx")

        assert "Paragraph one" in result
        assert "Paragraph two" in result

    def test_with_tables(self, tmp_path):
        mock_para = MagicMock()
        mock_para.text = "Intro"

        mock_cell1 = MagicMock()
        mock_cell1.text = "A1"
        mock_cell2 = MagicMock()
        mock_cell2.text = "B1"
        mock_row = MagicMock()
        mock_row.cells = [mock_cell1, mock_cell2]
        mock_table = MagicMock()
        mock_table.rows = [mock_row]

        mock_doc_obj = MagicMock()
        mock_doc_obj.paragraphs = [mock_para]
        mock_doc_obj.tables = [mock_table]

        mock_docx = MagicMock()
        mock_docx.Document.return_value = mock_doc_obj

        with patch.dict("sys.modules", {"docx": mock_docx}):
            result = _extract_docx(tmp_path / "test.docx")

        assert "A1 | B1" in result

    def test_fallback_zipfile(self, tmp_path):
        """When python-docx import fails, falls back to zipfile/XML."""
        docx_path = tmp_path / "test.docx"
        ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        xml_content = (
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<w:document xmlns:w="{ns}">'
            f"<w:body><w:p><w:r><w:t>Fallback text</w:t></w:r></w:p></w:body>"
            f"</w:document>"
        )
        with zipfile.ZipFile(docx_path, "w") as zf:
            zf.writestr("word/document.xml", xml_content)

        # Make docx import raise ImportError
        mock_docx = MagicMock()
        mock_docx.Document.side_effect = ImportError("no docx")

        with patch.dict("sys.modules", {"docx": mock_docx}):
            result = _extract_docx(docx_path)

        assert "Fallback text" in result


class TestExtractPdf:

    def _make_mock_pymupdf(self, pages_data):
        """Helper: returns a mock pymupdf module with given pages."""
        mock_pages = []
        for text in pages_data:
            p = MagicMock()
            p.get_text.return_value = text
            if not text.strip():
                pix = MagicMock()
                pix.tobytes.return_value = b"fake-png"
                p.get_pixmap.return_value = pix
            mock_pages.append(p)

        mock_doc = MagicMock()
        mock_doc.__len__ = MagicMock(return_value=len(mock_pages))
        mock_doc.__getitem__ = lambda self, i: mock_pages[i]
        mock_doc.close = MagicMock()

        mock_mod = MagicMock()
        mock_mod.open.return_value = mock_doc
        return mock_mod, mock_doc

    def test_with_pymupdf(self, tmp_path):
        mock_mod, mock_doc = self._make_mock_pymupdf(["PDF page content"])

        with patch.dict("sys.modules", {"pymupdf": mock_mod}):
            result = _extract_pdf(tmp_path / "test.pdf")

        assert "PDF page content" in result
        mock_doc.close.assert_called_once()

    def test_pymupdf_empty_page_triggers_ocr(self, tmp_path):
        mock_mod, _ = self._make_mock_pymupdf([""])

        with patch.dict("sys.modules", {"pymupdf": mock_mod}):
            with patch("worker._ocr_bytes", return_value="OCR result"):
                result = _extract_pdf(tmp_path / "test.pdf")

        assert "OCR" in result

    def test_empty_pdf(self, tmp_path):
        mock_mod, _ = self._make_mock_pymupdf([])

        with patch.dict("sys.modules", {"pymupdf": mock_mod}):
            result = _extract_pdf(tmp_path / "test.pdf")

        assert "empty PDF" in result

    def test_fallback_to_pypdf(self, tmp_path):
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "pypdf content"
        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]

        mock_pymupdf = MagicMock()
        mock_pymupdf.open.side_effect = ImportError("no pymupdf")

        mock_pypdf = MagicMock()
        mock_pypdf.PdfReader.return_value = mock_reader

        with patch.dict("sys.modules", {"pymupdf": mock_pymupdf, "pypdf": mock_pypdf}):
            result = _extract_pdf(tmp_path / "test.pdf")

        assert "pypdf content" in result

    def test_no_pdf_libs_available(self, tmp_path):
        mock_pymupdf = MagicMock()
        mock_pymupdf.open.side_effect = ImportError
        mock_pypdf = MagicMock()
        mock_pypdf.PdfReader.side_effect = ImportError

        with patch.dict("sys.modules", {"pymupdf": mock_pymupdf, "pypdf": mock_pypdf}):
            result = _extract_pdf(tmp_path / "test.pdf")

        assert "not available" in result


class TestExtractXlsx:

    def test_successful_extraction(self, tmp_path):
        mock_ws = MagicMock()
        mock_ws.iter_rows.return_value = [
            ("Name", "Age"),
            ("Alice", 30),
            ("Bob", None),
        ]

        mock_wb = MagicMock()
        mock_wb.sheetnames = ["Sheet1"]
        mock_wb.__getitem__ = MagicMock(return_value=mock_ws)
        mock_wb.close = MagicMock()

        mock_openpyxl = MagicMock()
        mock_openpyxl.load_workbook.return_value = mock_wb

        with patch.dict("sys.modules", {"openpyxl": mock_openpyxl}):
            result = _extract_xlsx(tmp_path / "test.xlsx")

        assert "Sheet1" in result
        assert "Name | Age" in result
        mock_wb.close.assert_called_once()

    def test_no_openpyxl(self, tmp_path):
        mock_openpyxl = MagicMock()
        mock_openpyxl.load_workbook.side_effect = ImportError

        with patch.dict("sys.modules", {"openpyxl": mock_openpyxl}):
            result = _extract_xlsx(tmp_path / "test.xlsx")

        assert "not available" in result


class TestOcrBytes:

    def test_successful_ocr(self):
        mock_img = MagicMock()
        mock_pil = MagicMock()
        mock_pil.Image.open.return_value = mock_img

        mock_tess = MagicMock()
        mock_tess.image_to_string.return_value = "OCR text here"

        with patch.dict("sys.modules", {"PIL": mock_pil, "PIL.Image": mock_pil.Image, "pytesseract": mock_tess}):
            result = _ocr_bytes(b"fake-image-bytes")

        assert result == "OCR text here"

    def test_empty_ocr_result(self):
        mock_img = MagicMock()
        mock_pil = MagicMock()
        mock_pil.Image.open.return_value = mock_img

        mock_tess = MagicMock()
        mock_tess.image_to_string.return_value = "  "

        with patch.dict("sys.modules", {"PIL": mock_pil, "PIL.Image": mock_pil.Image, "pytesseract": mock_tess}):
            result = _ocr_bytes(b"fake-image-bytes")

        assert "no text detected" in result

    def test_no_ocr_libs(self):
        # Remove PIL and pytesseract so import fails
        saved = {}
        for mod_name in ["pytesseract", "PIL", "PIL.Image"]:
            saved[mod_name] = sys.modules.pop(mod_name, None)

        real_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

        def fail_import(name, *args, **kwargs):
            if name in ("pytesseract", "PIL", "PIL.Image"):
                raise ImportError(f"no {name}")
            return real_import(name, *args, **kwargs)

        try:
            with patch("builtins.__import__", side_effect=fail_import):
                result = _ocr_bytes(b"bytes")
            assert "not available" in result or "OCR error" in result
        finally:
            for k, v in saved.items():
                if v is not None:
                    sys.modules[k] = v

    def test_ocr_exception(self):
        mock_img = MagicMock()
        mock_pil = MagicMock()
        mock_pil.Image.open.return_value = mock_img

        mock_tess = MagicMock()
        mock_tess.image_to_string.side_effect = RuntimeError("tesseract crashed")

        with patch.dict("sys.modules", {"PIL": mock_pil, "PIL.Image": mock_pil.Image, "pytesseract": mock_tess}):
            result = _ocr_bytes(b"bytes")

        assert "OCR error" in result


class TestExtractImageOcr:

    def test_reads_file_and_calls_ocr(self, tmp_path):
        img_file = tmp_path / "photo.png"
        img_file.write_bytes(b"fake-png-data")

        with patch("worker._ocr_bytes", return_value="Image text") as mock_ocr:
            result = _extract_image_ocr(img_file)

        assert result == "Image text"
        mock_ocr.assert_called_once_with(b"fake-png-data")


# ═══════════════════════════════════════════════════════════════
# _do_extract routing
# ═══════════════════════════════════════════════════════════════


class TestDoExtract:

    @pytest.mark.asyncio
    async def test_routes_plaintext(self, tmp_text_file):
        with patch("worker._extract_plaintext", return_value="plain") as mock:
            result = await _do_extract(tmp_text_file, "text/plain", "file.txt")
        mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_routes_markdown_by_ext(self, tmp_path):
        f = tmp_path / "readme.md"
        f.write_text("# Heading")
        with patch("worker._extract_plaintext", return_value="md") as mock:
            await _do_extract(f, "application/octet-stream", "readme.md")
        mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_routes_json_by_content_type(self, tmp_json_file):
        with patch("worker._extract_plaintext", return_value="json") as mock:
            await _do_extract(tmp_json_file, "application/json", "data.json")
        mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_routes_html(self, tmp_html_file):
        with patch("worker._extract_html", return_value="html") as mock:
            await _do_extract(tmp_html_file, "text/html", "page.html")
        mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_routes_csv(self, tmp_csv_file):
        with patch("worker._extract_csv", return_value="csv") as mock:
            await _do_extract(tmp_csv_file, "text/csv", "data.csv")
        mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_routes_tsv(self, tmp_tsv_file):
        with patch("worker._extract_csv", return_value="tsv") as mock:
            await _do_extract(tmp_tsv_file, "text/tab-separated-values", "data.tsv")
        mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_routes_docx(self, tmp_path):
        f = tmp_path / "doc.docx"
        f.write_bytes(b"fake")
        with patch("worker._extract_docx", return_value="docx") as mock:
            await _do_extract(f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "doc.docx")
        mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_routes_pdf(self, tmp_path):
        f = tmp_path / "doc.pdf"
        f.write_bytes(b"fake")
        with patch("worker._extract_pdf", return_value="pdf") as mock:
            await _do_extract(f, "application/pdf", "doc.pdf")
        mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_routes_xlsx(self, tmp_path):
        f = tmp_path / "data.xlsx"
        f.write_bytes(b"fake")
        with patch("worker._extract_xlsx", return_value="xlsx") as mock:
            await _do_extract(f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "data.xlsx")
        mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_routes_image(self, tmp_path):
        f = tmp_path / "photo.png"
        f.write_bytes(b"fake")
        with patch("worker._extract_image_ocr", return_value="ocr") as mock:
            await _do_extract(f, "image/png", "photo.png")
        mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_to_plaintext(self, tmp_path):
        f = tmp_path / "unknown.xyz"
        f.write_text("content")
        with patch("worker._extract_plaintext", return_value="fallback") as mock:
            await _do_extract(f, "application/octet-stream", "unknown.xyz")
        mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_routes_yaml_by_ext(self, tmp_path):
        f = tmp_path / "config.yaml"
        f.write_text("key: value")
        with patch("worker._extract_plaintext", return_value="yaml") as mock:
            await _do_extract(f, "application/octet-stream", "config.yaml")
        mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_routes_xls_by_ext(self, tmp_path):
        f = tmp_path / "old.xls"
        f.write_bytes(b"fake")
        with patch("worker._extract_xlsx", return_value="xls") as mock:
            await _do_extract(f, "application/vnd.ms-excel", "old.xls")
        mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_routes_image_by_ext_jpg(self, tmp_path):
        f = tmp_path / "photo.jpg"
        f.write_bytes(b"fake")
        with patch("worker._extract_image_ocr", return_value="ocr") as mock:
            await _do_extract(f, "application/octet-stream", "photo.jpg")
        mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_routes_htm_by_ext(self, tmp_path):
        f = tmp_path / "page.htm"
        f.write_text("<p>Hi</p>")
        with patch("worker._extract_html", return_value="htm") as mock:
            await _do_extract(f, "application/octet-stream", "page.htm")
        mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_routes_xml_by_content_type(self, tmp_path):
        f = tmp_path / "data.xml"
        f.write_text("<root/>")
        with patch("worker._extract_plaintext", return_value="xml") as mock:
            await _do_extract(f, "application/xml", "data.xml")
        mock.assert_called_once()


# ═══════════════════════════════════════════════════════════════
# Worker extract_text activity
# ═══════════════════════════════════════════════════════════════


class TestWorkerExtractTextActivity:

    @pytest.mark.asyncio
    async def test_file_not_found(self):
        task = DocumentTask("d1", "u1", "f.pdf", "/no/such/file.pdf", "application/pdf", "public")
        with patch("temporalio.activity.heartbeat"):
            result = await worker.extract_text(task)
        assert result.success is False
        assert "File not found" in result.error

    @pytest.mark.asyncio
    async def test_success(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("extracted content")
        task = DocumentTask("d1", "u1", "test.txt", str(f), "text/plain", "public")

        with patch("temporalio.activity.heartbeat"):
            with patch("worker._do_extract", return_value="extracted content"):
                result = await worker.extract_text(task)

        assert result.success is True
        assert result.extracted_text == "extracted content"

    @pytest.mark.asyncio
    async def test_exception_caught(self, tmp_path):
        f = tmp_path / "bad.txt"
        f.write_text("data")
        task = DocumentTask("d1", "u1", "bad.txt", str(f), "text/plain", "public")

        with patch("temporalio.activity.heartbeat"):
            with patch("worker._do_extract", side_effect=ValueError("boom")):
                result = await worker.extract_text(task)

        assert result.success is False
        assert "boom" in result.error


# ═══════════════════════════════════════════════════════════════
# Worker index_to_elasticsearch activity
# ═══════════════════════════════════════════════════════════════


class TestWorkerIndexActivity:

    @pytest.mark.asyncio
    async def test_success(self, mock_es):
        task = DocumentTask("d1", "u1", "f.pdf", "/tmp/f.pdf", "application/pdf", "public")
        extraction = ExtractionResult("d1", "text content", 12, True)

        with patch("temporalio.activity.heartbeat"):
            with patch("worker.Elasticsearch", return_value=mock_es):
                result = await worker.index_to_elasticsearch(task, extraction)

        assert result.indexed is True

    @pytest.mark.asyncio
    async def test_no_text_to_index(self):
        task = DocumentTask("d1", "u1", "f.pdf", "/tmp/f.pdf", "application/pdf", "public")
        extraction = ExtractionResult("d1", "", 0, False, "failed")

        with patch("temporalio.activity.heartbeat"):
            result = await worker.index_to_elasticsearch(task, extraction)

        assert result.indexed is False

    @pytest.mark.asyncio
    async def test_es_error(self):
        task = DocumentTask("d1", "u1", "f.pdf", "/tmp/f.pdf", "application/pdf", "public")
        extraction = ExtractionResult("d1", "text", 4, True)
        es = MagicMock()
        es.index.side_effect = ConnectionError("timeout")

        with patch("temporalio.activity.heartbeat"):
            with patch("worker.Elasticsearch", return_value=es):
                result = await worker.index_to_elasticsearch(task, extraction)

        assert result.indexed is False
        assert "timeout" in result.error


# ═══════════════════════════════════════════════════════════════
# Worker update_document_status activity
# ═══════════════════════════════════════════════════════════════


class TestWorkerUpdateStatus:

    @pytest.mark.asyncio
    async def test_success(self):
        mock_response = MagicMock(status_code=200)
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        with patch("temporalio.activity.heartbeat"):
            with patch("worker.httpx.AsyncClient") as MockClient:
                MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
                MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
                result = await worker.update_document_status("d1", "completed", "text")

        assert result is True

    @pytest.mark.asyncio
    async def test_failure(self):
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ConnectError("refused")

        with patch("temporalio.activity.heartbeat"):
            with patch("worker.httpx.AsyncClient") as MockClient:
                MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
                MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
                result = await worker.update_document_status("d1", "failed", "err")

        assert result is False


# ═══════════════════════════════════════════════════════════════
# Worker DocumentProcessingWorkflow
# ═══════════════════════════════════════════════════════════════


class TestWorkerWorkflow:

    @pytest.mark.asyncio
    async def test_happy_path(self):
        task = DocumentTask("d1", "u1", "f.pdf", "/tmp/f.pdf", "application/pdf", "public")
        extraction = ExtractionResult("d1", "content", 7, True)
        index_res = IndexResult("d1", True)

        returns = [extraction, index_res, True]
        idx = 0

        async def mock_ea(fn, *a, **kw):
            nonlocal idx
            r = returns[idx]; idx += 1
            return r

        with patch("temporalio.workflow.execute_activity", side_effect=mock_ea):
            with patch("temporalio.workflow.logger", MagicMock()):
                result = await worker.DocumentProcessingWorkflow().run(task)

        assert result["status"] == "completed"
        assert result["indexed"] is True

    @pytest.mark.asyncio
    async def test_extraction_failure(self):
        task = DocumentTask("d1", "u1", "f.pdf", "/tmp/f.pdf", "application/pdf", "public")
        extraction = ExtractionResult("d1", "", 0, False, "parse error")

        returns = [extraction, True]
        idx = 0

        async def mock_ea(fn, *a, **kw):
            nonlocal idx
            r = returns[idx]; idx += 1
            return r

        with patch("temporalio.workflow.execute_activity", side_effect=mock_ea):
            with patch("temporalio.workflow.logger", MagicMock()):
                result = await worker.DocumentProcessingWorkflow().run(task)

        assert result["status"] == "failed"


# ═══════════════════════════════════════════════════════════════
# run_worker startup
# ═══════════════════════════════════════════════════════════════


class TestRunWorker:

    @pytest.mark.asyncio
    async def test_exits_when_temporal_unreachable(self):
        with patch("worker.TemporalClient.connect", side_effect=ConnectionError("nope")):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(SystemExit) as exc_info:
                    await worker.run_worker()
        assert exc_info.value.code == 1

    @pytest.mark.asyncio
    async def test_connects_and_starts_worker(self):
        mock_temporal = AsyncMock()
        mock_worker = AsyncMock()
        mock_worker.run = AsyncMock()

        with patch("worker.TemporalClient.connect", return_value=mock_temporal):
            with patch("worker.Elasticsearch") as MockES:
                MockES.return_value.info.return_value = {"cluster_name": "test"}
                with patch("worker.Worker", return_value=mock_worker):
                    await worker.run_worker()

        mock_worker.run.assert_called_once()
