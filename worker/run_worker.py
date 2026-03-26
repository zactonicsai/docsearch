"""
DocMS Temporal Worker — entry point.

Connects to Temporal, registers the workflow + activities, and runs.
"""

import asyncio
import logging
import os
import sys

from elasticsearch import Elasticsearch
from temporalio.client import Client as TemporalClient
from temporalio.worker import Worker

from activities import extract_text, index_to_elasticsearch, update_document_status
from workflows import DocumentProcessingWorkflow

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("docms-worker")

TEMPORAL_HOST = os.getenv("TEMPORAL_HOST", "temporal:7233")
ES_URL = os.getenv("ELASTICSEARCH_URL", "http://elasticsearch:9200")
BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8080")
TASK_QUEUE = "document-processing"


async def run_worker():
    logger.info("=" * 50)
    logger.info("  DocMS Temporal Worker")
    logger.info(f"  Temporal: {TEMPORAL_HOST}")
    logger.info(f"  ES:       {ES_URL}")
    logger.info(f"  Backend:  {BACKEND_URL}")
    logger.info(f"  Queue:    {TASK_QUEUE}")
    logger.info("=" * 50)

    # Wait for Temporal
    client = None
    for attempt in range(60):
        try:
            client = await TemporalClient.connect(TEMPORAL_HOST)
            logger.info("Connected to Temporal server")
            break
        except Exception:
            if attempt % 10 == 0:
                logger.info(f"Waiting for Temporal... (attempt {attempt + 1})")
            await asyncio.sleep(2)

    if not client:
        logger.error("Could not connect to Temporal after 120s")
        sys.exit(1)

    # Wait for Elasticsearch
    for attempt in range(30):
        try:
            Elasticsearch(ES_URL).info()
            logger.info("Elasticsearch is reachable")
            break
        except Exception:
            if attempt % 5 == 0:
                logger.info(f"Waiting for Elasticsearch... (attempt {attempt + 1})")
            await asyncio.sleep(2)

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[DocumentProcessingWorkflow],
        activities=[extract_text, index_to_elasticsearch, update_document_status],
    )

    logger.info(f"Worker listening on queue '{TASK_QUEUE}'")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(run_worker())
