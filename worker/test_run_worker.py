"""Tests for run_worker.py — the standalone entry-point module."""

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestRunWorkerModule:
    """Tests for the run_worker.py entry-point module."""

    @pytest.mark.asyncio
    async def test_temporal_connection_failure_exits(self):
        """Worker exits with code 1 if Temporal is unreachable after retries."""
        from run_worker import run_worker

        with patch("run_worker.TemporalClient.connect", side_effect=ConnectionError("nope")):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(SystemExit) as exc_info:
                    await run_worker()

        assert exc_info.value.code == 1

    @pytest.mark.asyncio
    async def test_successful_startup(self):
        """Worker connects to Temporal, ES, then runs."""
        from run_worker import run_worker

        mock_temporal_client = AsyncMock()
        mock_worker_instance = AsyncMock()
        mock_worker_instance.run = AsyncMock()

        with patch("run_worker.TemporalClient.connect", return_value=mock_temporal_client):
            with patch("run_worker.Elasticsearch") as MockES:
                MockES.return_value.info.return_value = {"cluster_name": "test"}
                with patch("run_worker.Worker", return_value=mock_worker_instance):
                    await run_worker()

        mock_worker_instance.run.assert_called_once()

    @pytest.mark.asyncio
    async def test_es_retry_then_success(self):
        """Worker retries ES connection, then succeeds."""
        from run_worker import run_worker

        mock_temporal_client = AsyncMock()
        mock_worker_instance = AsyncMock()
        mock_worker_instance.run = AsyncMock()

        es_call_count = 0

        def es_info_side_effect():
            nonlocal es_call_count
            es_call_count += 1
            if es_call_count < 3:
                raise ConnectionError("ES not ready")
            return {"cluster_name": "test"}

        with patch("run_worker.TemporalClient.connect", return_value=mock_temporal_client):
            with patch("run_worker.Elasticsearch") as MockES:
                MockES.return_value.info.side_effect = es_info_side_effect
                with patch("run_worker.Worker", return_value=mock_worker_instance):
                    with patch("asyncio.sleep", new_callable=AsyncMock):
                        await run_worker()

        mock_worker_instance.run.assert_called_once()

    def test_task_queue_constant(self):
        """Task queue is correctly set."""
        from run_worker import TASK_QUEUE

        assert TASK_QUEUE == "document-processing"
