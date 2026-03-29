"""Shared pytest fixtures for DocMS worker tests."""

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure env vars are set before any module imports them at top-level
os.environ.setdefault("ELASTICSEARCH_URL", "http://localhost:9200")
os.environ.setdefault("BACKEND_URL", "http://localhost:8080")
os.environ.setdefault("TEMPORAL_HOST", "localhost:7233")


@pytest.fixture
def sample_task():
    """Factory fixture for DocumentTask instances."""
    from shared import DocumentTask

    def _make(
        document_id="doc-001",
        user_id="user-42",
        filename="report.pdf",
        file_path="/tmp/test/report.pdf",
        content_type="application/pdf",
        classification="public",
    ):
        return DocumentTask(
            document_id=document_id,
            user_id=user_id,
            filename=filename,
            file_path=file_path,
            content_type=content_type,
            classification=classification,
        )

    return _make


@pytest.fixture
def success_extraction():
    """Factory fixture for successful ExtractionResult."""
    from shared import ExtractionResult

    def _make(document_id="doc-001", text="Hello world extracted text", **kwargs):
        return ExtractionResult(
            document_id=document_id,
            extracted_text=text,
            char_count=len(text),
            success=True,
            **kwargs,
        )

    return _make


@pytest.fixture
def failed_extraction():
    """Factory fixture for failed ExtractionResult."""
    from shared import ExtractionResult

    def _make(document_id="doc-001", error="Something broke"):
        return ExtractionResult(
            document_id=document_id,
            extracted_text="",
            char_count=0,
            success=False,
            error=error,
        )

    return _make


@pytest.fixture
def tmp_text_file(tmp_path):
    """Create a temporary text file and return its path."""
    p = tmp_path / "sample.txt"
    p.write_text("Sample document content for testing.\nLine two.")
    return p


@pytest.fixture
def tmp_csv_file(tmp_path):
    """Create a temporary CSV file and return its path."""
    p = tmp_path / "data.csv"
    p.write_text("name,age,city\nAlice,30,NYC\nBob,25,LA\n")
    return p


@pytest.fixture
def tmp_tsv_file(tmp_path):
    """Create a temporary TSV file and return its path."""
    p = tmp_path / "data.tsv"
    p.write_text("name\tage\tcity\nAlice\t30\tNYC\n")
    return p


@pytest.fixture
def tmp_html_file(tmp_path):
    """Create a temporary HTML file and return its path."""
    p = tmp_path / "page.html"
    p.write_text(
        "<html><head><style>body{}</style></head>"
        "<body><h1>Title</h1><p>Content here</p>"
        "<script>alert(1)</script></body></html>"
    )
    return p


@pytest.fixture
def tmp_json_file(tmp_path):
    """Create a temporary JSON file."""
    p = tmp_path / "data.json"
    p.write_text('{"key": "value", "number": 42}')
    return p


@pytest.fixture
def mock_activity_heartbeat():
    """Patch activity.heartbeat so tests don't need a Temporal runtime."""
    with patch("temporalio.activity.heartbeat") as mock_hb:
        yield mock_hb


@pytest.fixture
def mock_es():
    """Return a mocked Elasticsearch client."""
    es = MagicMock()
    es.index.return_value = {"result": "created"}
    es.info.return_value = {"cluster_name": "test"}
    return es
