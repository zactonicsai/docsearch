"""
Workflow definition — runs inside the Temporal sandbox.

Uses imports_passed_through() so the sandbox doesn't try to
re-import heavy activity dependencies (httpx, elasticsearch, etc.).
"""

from datetime import timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from shared import DocumentTask, ExtractionResult, IndexResult
    from activities import extract_text, index_to_elasticsearch, update_document_status


@workflow.defn
class DocumentProcessingWorkflow:
    """
    Temporal workflow: Extract text → Index to ES → Update status.
    """

    @workflow.run
    async def run(self, task: DocumentTask) -> dict:
        workflow.logger.info(
            f"Starting workflow for {task.filename} (doc={task.document_id})"
        )

        # Step 1 — Extract text from file
        extraction: ExtractionResult = await workflow.execute_activity(
            extract_text,
            task,
            start_to_close_timeout=timedelta(minutes=10),
            heartbeat_timeout=timedelta(seconds=60),
        )

        if not extraction.success:
            await workflow.execute_activity(
                update_document_status,
                args=[task.document_id, "failed", extraction.error],
                start_to_close_timeout=timedelta(seconds=30),
            )
            return {
                "document_id": task.document_id,
                "status": "failed",
                "error": extraction.error,
            }

        # Step 2 — Index into Elasticsearch
        index_result: IndexResult = await workflow.execute_activity(
            index_to_elasticsearch,
            args=[task, extraction],
            start_to_close_timeout=timedelta(minutes=2),
            heartbeat_timeout=timedelta(seconds=30),
        )

        final_status = "completed" if index_result.indexed else "index_failed"

        # Step 3 — Callback to backend
        await workflow.execute_activity(
            update_document_status,
            args=[task.document_id, final_status, extraction.extracted_text],
            start_to_close_timeout=timedelta(seconds=30),
        )

        return {
            "document_id": task.document_id,
            "status": final_status,
            "chars_extracted": extraction.char_count,
            "indexed": index_result.indexed,
        }
