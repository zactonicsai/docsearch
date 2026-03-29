"""Enum that defines the two bucket categories."""

from enum import Enum


class BucketType(Enum):
    """
    SAFE  – long-lived storage, never auto-deleted.
    TEMP  – short-lived storage, cleaned up after use.

    Each member's value is the prefix added to bucket names
    so you can easily list / filter buckets by type.
    """

    SAFE = "safe-"
    TEMP = "temp-"

    def make_bucket_name(self, name: str) -> str:
        """Build the full bucket name: prefix + user-supplied name."""
        return f"{self.value}{name}"



"""Upload helpers that use S3BucketManager."""

from src.bucket_type import BucketType
from src.s3_manager import S3BucketManager


def upload_report_to_safe_bucket(filepath: str) -> str:
    """Upload a report to the long-lived SAFE bucket."""
    manager = S3BucketManager(BucketType.SAFE, "reports")
    manager.create_bucket()
    return manager.upload_file(filepath)


def upload_csv_to_temp_bucket(filepath: str) -> str:
    """Upload a CSV to a TEMP bucket for processing."""
    manager = S3BucketManager(BucketType.TEMP, "csv-imports")
    manager.create_bucket()
    return manager.upload_file(filepath, s3_key="incoming/data.csv")


def upload_raw_json(payload: bytes) -> str:
    """Upload raw JSON bytes to a TEMP bucket."""
    manager = S3BucketManager(BucketType.TEMP, "api-payloads")
    manager.create_bucket()
    return manager.upload_bytes(payload, s3_key="payload.json")


# ── Quick demo ────────────────────────────────────────
if __name__ == "__main__":
    key = upload_report_to_safe_bucket("quarterly_report.pdf")
    print(f"Uploaded to SAFE bucket with key: {key}")

##########################################################

"""Download helpers that use S3BucketManager."""

from pathlib import Path
from src.bucket_type import BucketType
from src.s3_manager import S3BucketManager


def download_report(s3_key: str, dest: str = "./downloads") -> Path:
    """Download a report from the SAFE bucket to a local folder."""
    manager = S3BucketManager(BucketType.SAFE, "reports")
    local_path = Path(dest) / s3_key
    return manager.download_file(s3_key, local_path)


def download_temp_csv_as_bytes(s3_key: str) -> bytes:
    """Download a CSV from the TEMP bucket as raw bytes."""
    manager = S3BucketManager(BucketType.TEMP, "csv-imports")
    return manager.download_bytes(s3_key)


def list_and_download_all(bucket_type: BucketType, name: str, dest: str) -> list[Path]:
    """List every object in a bucket, then download them all."""
    manager = S3BucketManager(bucket_type, name)
    paths: list[Path] = []
    for key in manager.list_objects():
        paths.append(manager.download_file(key, Path(dest) / key))
    return paths

#########################################################

"""Example: process a file then clean up the TEMP bucket."""

from src.bucket_type import BucketType
from src.s3_manager import S3BucketManager


def process_and_cleanup(filepath: str) -> None:
    """Upload → process → clean up.  A typical TEMP bucket lifecycle."""
    manager = S3BucketManager(BucketType.TEMP, "processing")
    manager.create_bucket()

    # 1. Upload
    key = manager.upload_file(filepath)

    # 2. Do your processing…
    data = manager.download_bytes(key)
    result = data.upper()  # placeholder for real work
    print(f"Processed {len(result)} bytes")

    # 3. Clean up all temp files
    deleted = manager.cleanup()
    print(f"Removed {deleted} temp objects")


# This will RAISE a ValueError — SAFE buckets can't be cleaned:
# safe_mgr = S3BucketManager(BucketType.SAFE, "reports")
# safe_mgr.cleanup()  → ValueError!