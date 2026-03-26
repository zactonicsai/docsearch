"""Shared dataclasses used by both workflow and activities."""

from dataclasses import dataclass


@dataclass
class DocumentTask:
    document_id: str
    user_id: str
    filename: str
    file_path: str
    content_type: str
    classification: str  # "public" | "private"


@dataclass
class ExtractionResult:
    document_id: str
    extracted_text: str
    char_count: int
    success: bool
    error: str = ""


@dataclass
class IndexResult:
    document_id: str
    indexed: bool
    error: str = ""
