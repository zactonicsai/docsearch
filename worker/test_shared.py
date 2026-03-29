"""Tests for shared.py — dataclasses used across the worker."""

import pytest
from shared import DocumentTask, ExtractionResult, IndexResult


class TestDocumentTask:
    """DocumentTask dataclass tests."""

    def test_create_with_all_fields(self):
        task = DocumentTask(
            document_id="d1",
            user_id="u1",
            filename="file.pdf",
            file_path="/tmp/file.pdf",
            content_type="application/pdf",
            classification="public",
        )
        assert task.document_id == "d1"
        assert task.user_id == "u1"
        assert task.filename == "file.pdf"
        assert task.file_path == "/tmp/file.pdf"
        assert task.content_type == "application/pdf"
        assert task.classification == "public"

    def test_equality(self):
        a = DocumentTask("d1", "u1", "f.pdf", "/tmp/f.pdf", "application/pdf", "public")
        b = DocumentTask("d1", "u1", "f.pdf", "/tmp/f.pdf", "application/pdf", "public")
        assert a == b

    def test_inequality(self):
        a = DocumentTask("d1", "u1", "f.pdf", "/tmp/f.pdf", "application/pdf", "public")
        b = DocumentTask("d2", "u1", "f.pdf", "/tmp/f.pdf", "application/pdf", "public")
        assert a != b

    def test_missing_field_raises(self):
        with pytest.raises(TypeError):
            DocumentTask(document_id="d1")  # missing required fields


class TestExtractionResult:
    """ExtractionResult dataclass tests."""

    def test_success_result(self):
        r = ExtractionResult(
            document_id="d1",
            extracted_text="hello",
            char_count=5,
            success=True,
        )
        assert r.success is True
        assert r.error == ""  # default
        assert r.char_count == 5

    def test_failure_result_with_error(self):
        r = ExtractionResult(
            document_id="d1",
            extracted_text="",
            char_count=0,
            success=False,
            error="File not found",
        )
        assert r.success is False
        assert r.error == "File not found"

    def test_default_error_is_empty_string(self):
        r = ExtractionResult("d1", "text", 4, True)
        assert r.error == ""


class TestIndexResult:
    """IndexResult dataclass tests."""

    def test_indexed_success(self):
        r = IndexResult(document_id="d1", indexed=True)
        assert r.indexed is True
        assert r.error == ""

    def test_indexed_failure(self):
        r = IndexResult(document_id="d1", indexed=False, error="ES down")
        assert r.indexed is False
        assert r.error == "ES down"

    def test_default_error_is_empty(self):
        r = IndexResult("d1", True)
        assert r.error == ""
