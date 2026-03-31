"""
AWSConfig – thin S3 façade with per-doc_id put tracking & bulk cleanup.

Usage – PDF image extraction pipeline
--------------------------------------
    from app.aws_config import AWSConfig
    from app.enums import AssetType, BucketType

    aws = AWSConfig()

    # ── store an extracted image ────────────────────────────────────
    aws.put_asset(
        doc_id="abc-123",
        asset_type=AssetType.IMAGE,
        page=4,
        image_index=0,
        body=png_bytes,
    )

    # ── store OCR text for that same image ──────────────────────────
    aws.put_asset(
        doc_id="abc-123",
        asset_type=AssetType.TEXT,
        page=4,
        image_index=0,
        body="The quick brown fox …",
    )

    # ── retrieve ────────────────────────────────────────────────────
    img = aws.get_asset("abc-123", AssetType.IMAGE, page=4, image_index=0)
    txt = aws.get_asset("abc-123", AssetType.TEXT,  page=4, image_index=0)

    # ── cleanup everything tracked for a doc_id ─────────────────────
    deleted = aws.cleanup("abc-123")
"""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from typing import Any, Optional

import boto3
from botocore.exceptions import ClientError

from app.enums import AssetType, BucketType
from app.key_builder import build_orig_key, build_temp_key

logger = logging.getLogger(__name__)

# Sensible content-type defaults per AssetType.
_CONTENT_TYPES: dict[AssetType, str] = {
    AssetType.IMAGE: "image/png",
    AssetType.TEXT: "text/plain; charset=utf-8",
}


class AWSConfig:
    """Centralised AWS / S3 configuration with upload tracking.

    Environment variables
    ---------------------
    AWS_REGION           – AWS region (default ``us-east-1``).
    S3_TEMP_BUCKET       – Bucket name for transient artefacts.
    S3_ORIG_BUCKET       – Bucket name for original documents.
    APP_ENV              – Deployment environment tag used in TEMP keys
                           (e.g. ``dev``, ``staging``, ``prod``).
    APP_INDEX            – Logical index / collection name used in TEMP keys.
    AWS_ENDPOINT_URL     – Optional endpoint override (for LocalStack / MinIO).
    """

    # ------------------------------------------------------------------ #
    #  Construction
    # ------------------------------------------------------------------ #
    def __init__(self) -> None:
        self.region: str = os.environ.get("AWS_REGION", "us-east-1")
        self.temp_bucket: str = os.environ["S3_TEMP_BUCKET"]
        self.orig_bucket: str = os.environ["S3_ORIG_BUCKET"]
        self.env: str = os.environ.get("APP_ENV", "dev")
        self.index: str = os.environ.get("APP_INDEX", "default")
        self.endpoint_url: Optional[str] = os.environ.get("AWS_ENDPOINT_URL")

        self._s3_client = self._build_client()

        # Track every key we put, grouped by doc_id.
        # {doc_id: [ (bucket_name, key), ... ]}
        self._tracked_puts: dict[str, list[tuple[str, str]]] = defaultdict(list)

    # ------------------------------------------------------------------ #
    #  Client factory
    # ------------------------------------------------------------------ #
    def _build_client(self) -> Any:
        kwargs: dict[str, Any] = {"region_name": self.region}
        if self.endpoint_url:
            kwargs["endpoint_url"] = self.endpoint_url
        return boto3.client("s3", **kwargs)

    # ------------------------------------------------------------------ #
    #  Bucket resolver
    # ------------------------------------------------------------------ #
    def _resolve_bucket(self, bucket_type: BucketType) -> str:
        if bucket_type is BucketType.TEMP:
            return self.temp_bucket
        return self.orig_bucket

    # ------------------------------------------------------------------ #
    #  Key resolver
    # ------------------------------------------------------------------ #
    def _resolve_key(
        self,
        bucket_type: BucketType,
        doc_id: str,
        *,
        asset_type: Optional[AssetType] = None,
        page: Optional[int] = None,
        image_index: Optional[int] = None,
        ext: Optional[str] = None,
        path: Optional[str] = None,
    ) -> str:
        if bucket_type is BucketType.TEMP:
            return build_temp_key(
                env=self.env,
                index=self.index,
                doc_id=doc_id,
                asset_type=asset_type,
                page=page,
                image_index=image_index,
                ext=ext,
                path=path,
            )
        return build_orig_key(doc_id=doc_id, path=path)

    # ------------------------------------------------------------------ #
    #  Internal _put / _get (shared by public methods)
    # ------------------------------------------------------------------ #
    def _put_object(
        self,
        bucket: str,
        key: str,
        doc_id: str,
        body: bytes | str,
        content_type: str,
        extra_args: Optional[dict[str, Any]] = None,
    ) -> str:
        put_kwargs: dict[str, Any] = {
            "Bucket": bucket,
            "Key": key,
            "Body": body.encode("utf-8") if isinstance(body, str) else body,
            "ContentType": content_type,
        }
        if extra_args:
            put_kwargs.update(extra_args)

        logger.info("PUT  s3://%s/%s", bucket, key)
        self._s3_client.put_object(**put_kwargs)

        self._tracked_puts[doc_id].append((bucket, key))
        return key

    def _get_object(self, bucket: str, key: str) -> bytes:
        logger.info("GET  s3://%s/%s", bucket, key)
        response = self._s3_client.get_object(Bucket=bucket, Key=key)
        return response["Body"].read()

    # ================================================================== #
    #  PUBLIC API – asset-oriented (PDF extraction pipeline)
    # ================================================================== #

    def put_asset(
        self,
        doc_id: str,
        asset_type: AssetType,
        page: int,
        image_index: int,
        body: bytes | str,
        *,
        ext: Optional[str] = None,
        content_type: Optional[str] = None,
        extra_args: Optional[dict[str, Any]] = None,
    ) -> str:
        """Upload an extracted page asset (image or OCR text) to TEMP.

        Key produced::

            {env}/{index}/{doc_id}/{asset_type}/page_{page}/{image_index}.{ext}

        Returns the computed S3 key.
        """
        bucket = self._resolve_bucket(BucketType.TEMP)
        key = self._resolve_key(
            BucketType.TEMP,
            doc_id,
            asset_type=asset_type,
            page=page,
            image_index=image_index,
            ext=ext,
        )
        ct = content_type or _CONTENT_TYPES.get(asset_type, "application/octet-stream")
        return self._put_object(bucket, key, doc_id, body, ct, extra_args)

    def get_asset(
        self,
        doc_id: str,
        asset_type: AssetType,
        page: int,
        image_index: int,
        *,
        ext: Optional[str] = None,
    ) -> bytes:
        """Download an extracted page asset from TEMP."""
        bucket = self._resolve_bucket(BucketType.TEMP)
        key = self._resolve_key(
            BucketType.TEMP,
            doc_id,
            asset_type=asset_type,
            page=page,
            image_index=image_index,
            ext=ext,
        )
        return self._get_object(bucket, key)

    # ================================================================== #
    #  PUBLIC API – generic put / get (backward-compatible)
    # ================================================================== #

    def put(
        self,
        bucket_type: BucketType,
        doc_id: str,
        body: bytes | str,
        *,
        path: Optional[str] = None,
        content_type: str = "application/octet-stream",
        extra_args: Optional[dict[str, Any]] = None,
    ) -> str:
        """Upload *body* to S3 using a free-form path and track under *doc_id*.

        For page-level image/text assets prefer :meth:`put_asset`.

        Returns the computed S3 key.
        """
        bucket = self._resolve_bucket(bucket_type)
        key = self._resolve_key(bucket_type, doc_id, path=path)
        return self._put_object(bucket, key, doc_id, body, content_type, extra_args)

    def get(
        self,
        bucket_type: BucketType,
        doc_id: str,
        *,
        path: Optional[str] = None,
    ) -> bytes:
        """Download an object from S3 using a free-form path."""
        bucket = self._resolve_bucket(bucket_type)
        key = self._resolve_key(bucket_type, doc_id, path=path)
        return self._get_object(bucket, key)

    # ================================================================== #
    #  PUBLIC API – cleanup
    # ================================================================== #

    def cleanup(self, doc_id: str) -> list[str]:
        """Delete every S3 object that was ``put`` / ``put_asset`` under *doc_id*.

        Returns a list of keys that were successfully deleted.
        """
        entries = self._tracked_puts.pop(doc_id, [])
        if not entries:
            logger.info("cleanup(%s): nothing tracked – no-op", doc_id)
            return []

        deleted_keys: list[str] = []
        for bucket, key in entries:
            try:
                logger.info("DELETE s3://%s/%s", bucket, key)
                self._s3_client.delete_object(Bucket=bucket, Key=key)
                deleted_keys.append(key)
            except ClientError:
                logger.exception("Failed to delete s3://%s/%s", bucket, key)

        return deleted_keys

    # ------------------------------------------------------------------ #
    #  Introspection helpers
    # ------------------------------------------------------------------ #
    def tracked_keys(self, doc_id: str) -> list[tuple[str, str]]:
        """Return a *copy* of tracked ``(bucket, key)`` pairs for *doc_id*."""
        return list(self._tracked_puts.get(doc_id, []))

    @property
    def all_tracked_doc_ids(self) -> list[str]:
        """Return every doc_id that currently has tracked puts."""
        return list(self._tracked_puts.keys())
