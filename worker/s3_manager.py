"""Reusable S3 bucket manager with SAFE / TEMP support."""

from __future__ import annotations

import logging
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from .bucket_type import BucketType

logger = logging.getLogger(__name__)


class S3BucketManager:
    """Manage uploads, downloads, and cleanup for a single S3 bucket.

    Args:
        bucket_type: Whether this is a SAFE or TEMP bucket.
        name:        A short, descriptive name (e.g. "reports", "uploads").
        region:      AWS region for the bucket.  Defaults to us-east-1.
    """

    def __init__(
        self,
        bucket_type: BucketType,
        name: str,
        region: str = "us-east-1",
    ) -> None:
        self.bucket_type = bucket_type
        self.bucket_name = bucket_type.make_bucket_name(name)
        self.region = region
        self._client = boto3.client("s3", region_name=region)

    # ── Bucket lifecycle ──────────────────────────────────

    def create_bucket(self) -> None:
        """Create the S3 bucket if it does not already exist."""
        try:
            if self.region == "us-east-1":
                self._client.create_bucket(Bucket=self.bucket_name)
            else:
                self._client.create_bucket(
                    Bucket=self.bucket_name,
                    CreateBucketConfiguration={
                        "LocationConstraint": self.region,
                    },
                )
            logger.info("Created bucket %s", self.bucket_name)
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "BucketAlreadyOwnedByYou":
                logger.info("Bucket %s already exists", self.bucket_name)
            else:
                raise

    # ── Upload ────────────────────────────────────────────

    def upload_file(
        self, local_path: str | Path, s3_key: str | None = None,
    ) -> str:
        """Upload a local file to the bucket.

        Args:
            local_path: Path to the file on disk.
            s3_key:     Object key in S3.  Defaults to the filename.

        Returns:
            The S3 key that was written.
        """
        local_path = Path(local_path)
        if not local_path.is_file():
            raise FileNotFoundError(f"No such file: {local_path}")

        key = s3_key or local_path.name
        self._client.upload_file(
            Filename=str(local_path),
            Bucket=self.bucket_name,
            Key=key,
        )
        logger.info("Uploaded %s → s3://%s/%s", local_path, self.bucket_name, key)
        return key

    def upload_bytes(
        self, data: bytes, s3_key: str,
    ) -> str:
        """Upload raw bytes directly to S3."""
        self._client.put_object(
            Bucket=self.bucket_name, Key=s3_key, Body=data,
        )
        logger.info("Uploaded %d bytes → s3://%s/%s", len(data), self.bucket_name, s3_key)
        return s3_key

    # ── Download ──────────────────────────────────────────

    def download_file(
        self, s3_key: str, local_path: str | Path,
    ) -> Path:
        """Download an S3 object to a local file.

        Returns:
            The Path of the downloaded file.
        """
        local_path = Path(local_path)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        self._client.download_file(
            Bucket=self.bucket_name, Key=s3_key, Filename=str(local_path),
        )
        logger.info("Downloaded s3://%s/%s → %s", self.bucket_name, s3_key, local_path)
        return local_path

    def download_bytes(self, s3_key: str) -> bytes:
        """Download an S3 object as raw bytes."""
        response = self._client.get_object(
            Bucket=self.bucket_name, Key=s3_key,
        )
        return response["Body"].read()

    # ── Listing ───────────────────────────────────────────

    def list_objects(self, prefix: str = "") -> list[str]:
        """Return a list of S3 keys in the bucket."""
        paginator = self._client.get_paginator("list_objects_v2")
        keys: list[str] = []
        for page in paginator.paginate(Bucket=self.bucket_name, Prefix=prefix):
            for obj in page.get("Contents", []):
                keys.append(obj["Key"])
        return keys

    # ── Cleanup (TEMP buckets only) ───────────────────────

    def cleanup(self) -> int:
        """Delete ALL objects in a TEMP bucket.

        Raises:
            ValueError: If called on a SAFE bucket.

        Returns:
            The number of objects deleted.
        """
        if self.bucket_type is not BucketType.TEMP:
            raise ValueError(
                f"cleanup() is only allowed on TEMP buckets, "
                f"got {self.bucket_type.name}"
            )

        keys = self.list_objects()
        if not keys:
            logger.info("Bucket %s is already empty", self.bucket_name)
            return 0

        # S3 delete_objects accepts up to 1 000 keys at a time
        deleted = 0
        for i in range(0, len(keys), 1000):
            batch = keys[i : i + 1000]
            self._client.delete_objects(
                Bucket=self.bucket_name,
                Delete={"Objects": [{"Key": k} for k in batch]},
            )
            deleted += len(batch)

        logger.info("Cleaned up %d objects from %s", deleted, self.bucket_name)
        return deleted