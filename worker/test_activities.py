"""Tests for activities.py — extract_text, index_to_elasticsearch, update_document_status."""

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from shared import DocumentTask, ExtractionResult, IndexResult


# ═══════════════════════════════════════════════════════════════
# extract_text activity
# ═══════════════════════════════════════════════════════════════


class TestExtractTextActivity:
    """Tests for the extract_text activity function."""

    @pytest.mark.asyncio
    async def test_file_not_found_returns_failure(self, sample_task, mock_activity_heartbeat):
        from activities import extract_text

        task = sample_task(file_path="/nonexistent/path/file.pdf")
        result = await extract_text(task)

        assert result.success is False
        assert "File not found" in result.error
        assert result.char_count == 0
        assert result.extracted_text == ""

    @pytest.mark.asyncio
    async def test_successful_extraction(self, sample_task, tmp_text_file, mock_activity_heartbeat):
        from activities import extract_text

        task = sample_task(
            filename="sample.txt",
            file_path=str(tmp_text_file),
            content_type="text/plain",
        )

        with patch("activities._extract_with_unstructured", return_value="Extracted content here"):
            result = await extract_text(task)

        assert result.success is True
        assert result.extracted_text == "Extracted content here"
        assert result.char_count == len("Extracted content here")
        assert result.document_id == "doc-001"

    @pytest.mark.asyncio
    async def test_extraction_exception_returns_failure(
        self, sample_task, tmp_text_file, mock_activity_heartbeat
    ):
        from activities import extract_text

        task = sample_task(
            filename="sample.txt",
            file_path=str(tmp_text_file),
            content_type="text/plain",
        )

        with patch(
            "activities._extract_with_unstructured",
            side_effect=RuntimeError("parser crashed"),
        ):
            result = await extract_text(task)

        assert result.success is False
        assert "parser crashed" in result.error

    @pytest.mark.asyncio
    async def test_extraction_strips_whitespace(self, sample_task, tmp_text_file, mock_activity_heartbeat):
        from activities import extract_text

        task = sample_task(
            filename="sample.txt",
            file_path=str(tmp_text_file),
            content_type="text/plain",
        )

        with patch("activities._extract_with_unstructured", return_value="  padded text  \n\n"):
            result = await extract_text(task)

        assert result.extracted_text == "padded text"

    @pytest.mark.asyncio
    async def test_heartbeat_called(self, sample_task, tmp_text_file, mock_activity_heartbeat):
        from activities import extract_text

        task = sample_task(
            filename="sample.txt",
            file_path=str(tmp_text_file),
            content_type="text/plain",
        )

        with patch("activities._extract_with_unstructured", return_value="text"):
            await extract_text(task)

        assert mock_activity_heartbeat.call_count >= 1


# ═══════════════════════════════════════════════════════════════
# _extract_with_unstructured helper
# ═══════════════════════════════════════════════════════════════


class TestExtractWithUnstructured:
    """Tests for the _extract_with_unstructured helper.

    partition() is imported locally inside the function via
    `from unstructured.partition.auto import partition`.
    We inject mock modules into sys.modules before patching.
    """

    @pytest.fixture(autouse=True)
    def _inject_unstructured_mock(self):
        """Pre-register mock unstructured modules so patch() can resolve them."""
        mock_auto = MagicMock()
        mods = {
            "unstructured": MagicMock(),
            "unstructured.partition": MagicMock(),
            "unstructured.partition.auto": mock_auto,
        }
        with patch.dict("sys.modules", mods):
            self._mock_auto = mock_auto
            yield

    def test_joins_element_texts(self, tmp_text_file):
        from activities import _extract_with_unstructured

        mock_el1 = MagicMock()
        mock_el1.text = "First paragraph"
        type(mock_el1).__name__ = "NarrativeText"

        mock_el2 = MagicMock()
        mock_el2.text = "Second paragraph"
        type(mock_el2).__name__ = "NarrativeText"

        self._mock_auto.partition.return_value = [mock_el1, mock_el2]
        result = _extract_with_unstructured(tmp_text_file, "sample.txt")

        assert "First paragraph" in result
        assert "Second paragraph" in result
        assert "\n\n" in result

    def test_empty_elements_returns_no_content(self, tmp_text_file):
        from activities import _extract_with_unstructured

        self._mock_auto.partition.return_value = []
        result = _extract_with_unstructured(tmp_text_file, "sample.txt")

        assert result == "(no content extracted)"

    def test_skips_empty_text_elements(self, tmp_text_file):
        from activities import _extract_with_unstructured

        el_good = MagicMock()
        el_good.text = "Real content"
        type(el_good).__name__ = "NarrativeText"

        el_empty = MagicMock()
        el_empty.text = "   "
        type(el_empty).__name__ = "NarrativeText"

        el_none = MagicMock(spec=[])  # no .text attribute

        self._mock_auto.partition.return_value = [el_good, el_empty, el_none]
        result = _extract_with_unstructured(tmp_text_file, "sample.txt")

        assert result == "Real content"


# ═══════════════════════════════════════════════════════════════
# index_to_elasticsearch activity
# ═══════════════════════════════════════════════════════════════


class TestIndexToElasticsearch:
    """Tests for the index_to_elasticsearch activity."""

    @pytest.mark.asyncio
    async def test_successful_indexing(
        self, sample_task, success_extraction, mock_activity_heartbeat, mock_es
    ):
        from activities import index_to_elasticsearch

        task = sample_task()
        extraction = success_extraction()

        with patch("activities.Elasticsearch", return_value=mock_es):
            result = await index_to_elasticsearch(task, extraction)

        assert result.indexed is True
        assert result.error == ""
        mock_es.index.assert_called_once()
        call_kwargs = mock_es.index.call_args
        assert call_kwargs.kwargs["index"] == "documents"
        assert call_kwargs.kwargs["id"] == "doc-001"

    @pytest.mark.asyncio
    async def test_skips_indexing_when_extraction_failed(
        self, sample_task, failed_extraction, mock_activity_heartbeat
    ):
        from activities import index_to_elasticsearch

        task = sample_task()
        extraction = failed_extraction()

        result = await index_to_elasticsearch(task, extraction)

        assert result.indexed is False
        assert "No text to index" in result.error

    @pytest.mark.asyncio
    async def test_skips_indexing_when_no_text(
        self, sample_task, mock_activity_heartbeat
    ):
        from activities import index_to_elasticsearch

        task = sample_task()
        extraction = ExtractionResult(
            document_id="doc-001",
            extracted_text="",
            char_count=0,
            success=True,
        )

        result = await index_to_elasticsearch(task, extraction)
        assert result.indexed is False

    @pytest.mark.asyncio
    async def test_es_exception_returns_failure(
        self, sample_task, success_extraction, mock_activity_heartbeat
    ):
        from activities import index_to_elasticsearch

        task = sample_task()
        extraction = success_extraction()
        mock_es = MagicMock()
        mock_es.index.side_effect = ConnectionError("ES unreachable")

        with patch("activities.Elasticsearch", return_value=mock_es):
            result = await index_to_elasticsearch(task, extraction)

        assert result.indexed is False
        assert "ES unreachable" in result.error

    @pytest.mark.asyncio
    async def test_indexed_document_contains_classification(
        self, sample_task, success_extraction, mock_activity_heartbeat, mock_es
    ):
        from activities import index_to_elasticsearch

        task = sample_task(classification="private")
        extraction = success_extraction()

        with patch("activities.Elasticsearch", return_value=mock_es):
            await index_to_elasticsearch(task, extraction)

        doc_body = mock_es.index.call_args.kwargs["document"]
        assert doc_body["classification"] == "private"
        assert doc_body["user_id"] == "user-42"


# ═══════════════════════════════════════════════════════════════
# update_document_status activity
# ═══════════════════════════════════════════════════════════════


class TestUpdateDocumentStatus:
    """Tests for the update_document_status activity."""

    @pytest.mark.asyncio
    async def test_successful_status_update(self, mock_activity_heartbeat):
        from activities import update_document_status

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("activities.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await update_document_status("doc-001", "completed", "some text")

        assert result is True
        mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_non_200_returns_false(self, mock_activity_heartbeat):
        from activities import update_document_status

        mock_response = MagicMock()
        mock_response.status_code = 500

        with patch("activities.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await update_document_status("doc-001", "completed", "text")

        assert result is False

    @pytest.mark.asyncio
    async def test_network_error_returns_false(self, mock_activity_heartbeat):
        from activities import update_document_status

        with patch("activities.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.side_effect = httpx.ConnectError("refused")
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await update_document_status("doc-001", "failed", "err")

        assert result is False

    @pytest.mark.asyncio
    async def test_text_truncated_to_50k(self, mock_activity_heartbeat):
        from activities import update_document_status

        long_text = "x" * 100_000
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("activities.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            await update_document_status("doc-001", "completed", long_text)

        call_json = mock_client.post.call_args.kwargs["json"]
        assert len(call_json["extracted_text"]) == 50_000
