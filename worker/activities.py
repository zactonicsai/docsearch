"""
Activities for document processing — powered by Unstructured.

Uses unstructured.partition.auto.partition() which auto-detects
file type and routes to the correct parser:

  PDF  → pdfminer / tesseract OCR
  DOCX → python-docx
  DOC  → libreoffice conversion
  PPTX → python-pptx
  XLSX → openpyxl
  CSV  → csv module
  HTML → lxml
  TXT/MD/RST/RTF → direct read
  Images (PNG/JPG/TIFF) → tesseract OCR
  EPUB, ODT, ORG → pandoc/native parsers

All heavy imports stay here — outside the Temporal workflow sandbox.
"""

import logging
import os
from pathlib import Path

import httpx
from elasticsearch import Elasticsearch
from temporalio import activity

from shared import DocumentTask, ExtractionResult, IndexResult

logger = logging.getLogger("docms-activities")

ES_URL = os.getenv("ELASTICSEARCH_URL", "http://elasticsearch:9200")
BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8080")
ES_INDEX = "documents"


# ── Extract Text Activity ────────────────────────────────────

@activity.defn
async def extract_text(task: DocumentTask) -> ExtractionResult:
    """
    Extract plain text from any supported document using Unstructured.

    Unstructured's partition() auto-detects the file type from the
    filename extension and file contents, then routes to the correct
    parser. Supported types include:
      .pdf .docx .doc .pptx .ppt .xlsx .xls .csv .tsv
      .html .htm .xml .json .txt .md .rst .rtf .epub .odt .org
      .png .jpg .jpeg .tiff .tif .bmp .heic
    """
    logger.info(f"Extracting text from {task.filename} ({task.content_type})")
    activity.heartbeat("starting extraction")

    file_path = Path(task.file_path)
    if not file_path.exists():
        return ExtractionResult(
            document_id=task.document_id,
            extracted_text="",
            char_count=0,
            success=False,
            error=f"File not found: {task.file_path}",
        )

    try:
        text = _extract_with_unstructured(file_path, task.filename)
        text = text.strip()
        logger.info(f"Extracted {len(text)} chars from {task.filename}")
        activity.heartbeat("extraction complete")
        return ExtractionResult(
            document_id=task.document_id,
            extracted_text=text,
            char_count=len(text),
            success=True,
        )
    except Exception as e:
        logger.error(f"Extraction failed for {task.filename}: {e}", exc_info=True)
        return ExtractionResult(
            document_id=task.document_id,
            extracted_text="",
            char_count=0,
            success=False,
            error=str(e),
        )


def _extract_with_unstructured(file_path: Path, filename: str) -> str:
    """
    Use unstructured's partition() to parse any document.

    partition() returns a list of Element objects (Title, NarrativeText,
    ListItem, Table, Image, etc.). We join their .text to get full content.
    """
    from unstructured.partition.auto import partition

    logger.info(f"Running unstructured partition on {filename}")

    elements = partition(
        filename=str(file_path),
        # Use hi_res strategy for PDFs (better layout detection + OCR)
        strategy="hi_res",
        # Include page breaks to preserve document structure
        include_page_breaks=False,
        # OCR languages
        languages=["eng"],
    )

    if not elements:
        logger.warning(f"No elements extracted from {filename}")
        return "(no content extracted)"

    # Log element type breakdown
    type_counts = {}
    for el in elements:
        t = type(el).__name__
        type_counts[t] = type_counts.get(t, 0) + 1
    logger.info(f"Extracted {len(elements)} elements: {type_counts}")

    # Join all element text with double newlines between sections
    texts = []
    for el in elements:
        if hasattr(el, "text") and el.text and el.text.strip():
            texts.append(el.text.strip())

    return "\n\n".join(texts)


# ── Index to Elasticsearch Activity ──────────────────────────

@activity.defn
async def index_to_elasticsearch(
    task: DocumentTask, extraction: ExtractionResult
) -> IndexResult:
    """Index extracted text into Elasticsearch with classification."""
    logger.info(f"Indexing {task.document_id} into ES (class={task.classification})")
    activity.heartbeat("indexing")

    if not extraction.success or not extraction.extracted_text:
        return IndexResult(
            document_id=task.document_id, indexed=False, error="No text to index"
        )

    try:
        es = Elasticsearch(ES_URL)
        es.index(
            index=ES_INDEX,
            id=task.document_id,
            document={
                "doc_id": task.document_id,
                "user_id": task.user_id,
                "filename": task.filename,
                "classification": task.classification,
                "content": extraction.extracted_text,
                "content_type": task.content_type,
                "indexed_at": "now",
            },
            refresh="true",
        )
        logger.info(f"Document {task.document_id} indexed successfully")
        return IndexResult(document_id=task.document_id, indexed=True)
    except Exception as e:
        logger.error(f"ES indexing failed: {e}")
        return IndexResult(
            document_id=task.document_id, indexed=False, error=str(e)
        )


# ── Update Status Activity ───────────────────────────────────

@activity.defn
async def update_document_status(
    document_id: str, status: str, extracted_text: str
) -> bool:
    """Callback to Go backend with processing result."""
    logger.info(f"Updating {document_id} → '{status}'")
    activity.heartbeat("updating status")
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{BACKEND_URL}/internal/update-status",
                json={
                    "document_id": document_id,
                    "status": status,
                    "extracted_text": extracted_text[:50000],
                },
                timeout=10,
            )
            return resp.status_code == 200
    except Exception as e:
        logger.warning(f"Status update failed (non-fatal): {e}")
        return False
