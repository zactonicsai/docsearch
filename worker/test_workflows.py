"""Tests for workflows.py — DocumentProcessingWorkflow."""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from shared import DocumentTask, ExtractionResult, IndexResult


# ═══════════════════════════════════════════════════════════════
# DocumentProcessingWorkflow
# ═══════════════════════════════════════════════════════════════


class TestDocumentProcessingWorkflow:
    """
    Unit tests for the workflow logic.

    We mock workflow.execute_activity to isolate the orchestration
    logic without needing a real Temporal server.
    """

    def _make_task(self, **overrides):
        defaults = dict(
            document_id="doc-001",
            user_id="user-42",
            filename="report.pdf",
            file_path="/tmp/report.pdf",
            content_type="application/pdf",
            classification="public",
        )
        defaults.update(overrides)
        return DocumentTask(**defaults)

    @pytest.mark.asyncio
    async def test_happy_path_completed(self):
        """Full success: extract → index → status=completed."""
        from workflows import DocumentProcessingWorkflow

        task = self._make_task()
        extraction = ExtractionResult(
            document_id="doc-001",
            extracted_text="Hello world",
            char_count=11,
            success=True,
        )
        index_result = IndexResult(document_id="doc-001", indexed=True)

        activity_returns = [extraction, index_result, True]
        call_index = 0

        async def mock_execute_activity(activity_fn, *args, **kwargs):
            nonlocal call_index
            result = activity_returns[call_index]
            call_index += 1
            return result

        with patch("temporalio.workflow.execute_activity", side_effect=mock_execute_activity):
            with patch("temporalio.workflow.logger", MagicMock()):
                wf = DocumentProcessingWorkflow()
                result = await wf.run(task)

        assert result["status"] == "completed"
        assert result["document_id"] == "doc-001"
        assert result["chars_extracted"] == 11
        assert result["indexed"] is True

    @pytest.mark.asyncio
    async def test_extraction_failure_returns_failed(self):
        """When extraction fails, workflow reports failed and updates status."""
        from workflows import DocumentProcessingWorkflow

        task = self._make_task()
        extraction = ExtractionResult(
            document_id="doc-001",
            extracted_text="",
            char_count=0,
            success=False,
            error="parser error",
        )

        activity_returns = [extraction, True]  # extract, update_status
        call_index = 0

        async def mock_execute_activity(activity_fn, *args, **kwargs):
            nonlocal call_index
            result = activity_returns[call_index]
            call_index += 1
            return result

        with patch("temporalio.workflow.execute_activity", side_effect=mock_execute_activity):
            with patch("temporalio.workflow.logger", MagicMock()):
                wf = DocumentProcessingWorkflow()
                result = await wf.run(task)

        assert result["status"] == "failed"
        assert result["error"] == "parser error"
        # Should only have called 2 activities (extract + update_status), not index
        assert call_index == 2

    @pytest.mark.asyncio
    async def test_index_failure_returns_index_failed(self):
        """When indexing fails, workflow reports index_failed."""
        from workflows import DocumentProcessingWorkflow

        task = self._make_task()
        extraction = ExtractionResult(
            document_id="doc-001",
            extracted_text="Content",
            char_count=7,
            success=True,
        )
        index_result = IndexResult(document_id="doc-001", indexed=False, error="ES down")

        activity_returns = [extraction, index_result, True]
        call_index = 0

        async def mock_execute_activity(activity_fn, *args, **kwargs):
            nonlocal call_index
            result = activity_returns[call_index]
            call_index += 1
            return result

        with patch("temporalio.workflow.execute_activity", side_effect=mock_execute_activity):
            with patch("temporalio.workflow.logger", MagicMock()):
                wf = DocumentProcessingWorkflow()
                result = await wf.run(task)

        assert result["status"] == "index_failed"
        assert result["indexed"] is False
        assert call_index == 3  # all 3 activities called

    @pytest.mark.asyncio
    async def test_result_contains_document_id(self):
        """Result dict always contains the document_id."""
        from workflows import DocumentProcessingWorkflow

        task = self._make_task(document_id="custom-id-99")
        extraction = ExtractionResult("custom-id-99", "text", 4, True)
        index_result = IndexResult("custom-id-99", True)

        returns = [extraction, index_result, True]
        idx = 0

        async def mock_ea(fn, *a, **kw):
            nonlocal idx
            r = returns[idx]
            idx += 1
            return r

        with patch("temporalio.workflow.execute_activity", side_effect=mock_ea):
            with patch("temporalio.workflow.logger", MagicMock()):
                wf = DocumentProcessingWorkflow()
                result = await wf.run(task)

        assert result["document_id"] == "custom-id-99"
