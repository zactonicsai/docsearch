"""
Deterministic S3 key construction for TEMP and ORIG bucket types.

TEMP key anatomy (PDF image/text extraction)
─────────────────────────────────────────────
  {env}/{index}/{doc_id}/{asset_type}/page_{page}/{image_index}.{ext}

Examples:
  dev/search_idx/abc-123/image/page_4/0.png      ← 1st image on page 4
  dev/search_idx/abc-123/image/page_4/1.png      ← 2nd image on page 4
  dev/search_idx/abc-123/text/page_4/0.txt        ← OCR text for 1st image
  dev/search_idx/abc-123/text/page_4/1.txt        ← OCR text for 2nd image

Generic TEMP key (no asset_type)
────────────────────────────────
  {env}/{index}/{doc_id}
  {env}/{index}/{doc_id}/{path}

ORIG key
────────
  {doc_id}
  {doc_id}/{path}
"""

from __future__ import annotations

from typing import Optional

from app.enums import AssetType

# Default file extensions per asset type.
_DEFAULT_EXT: dict[AssetType, str] = {
    AssetType.IMAGE: "png",
    AssetType.TEXT: "txt",
}


def build_temp_key(
    env: str,
    index: str,
    doc_id: str,
    asset_type: Optional[AssetType] = None,
    page: Optional[int] = None,
    image_index: Optional[int] = None,
    ext: Optional[str] = None,
    path: Optional[str] = None,
) -> str:
    """Build an S3 object key for the TEMP bucket.

    There are two calling modes:

    1.  **Asset mode** (``asset_type`` provided) – for PDF page-level
        extraction.  ``page`` and ``image_index`` become required.

        Key: ``{env}/{index}/{doc_id}/{asset_type}/page_{page}/{image_index}.{ext}``

    2.  **Generic mode** (no ``asset_type``) – free-form path under doc_id.

        Key: ``{env}/{index}/{doc_id}[/{path}]``

    Parameters
    ----------
    env          : Deployment environment (``"dev"``, ``"prod"``).
    index        : Logical index / collection name.
    doc_id       : Unique document identifier.
    asset_type   : ``AssetType.IMAGE`` or ``AssetType.TEXT``.
    page         : PDF page number (required in asset mode).
    image_index  : 0-based position of the image on the page
                   (required in asset mode).
    ext          : File extension override (default per asset type).
    path         : Free-form sub-path (generic mode only).

    Raises
    ------
    ValueError
        On incompatible parameter combinations.
    """

    # ── Asset mode ───────────────────────────────────────────────────
    if asset_type is not None:
        if page is None:
            raise ValueError("`page` is required when `asset_type` is specified")
        if image_index is None:
            raise ValueError(
                "`image_index` is required when `asset_type` is specified"
            )
        if path is not None:
            raise ValueError(
                "`path` cannot be used together with `asset_type` – "
                "use `page` / `image_index` instead"
            )

        file_ext = ext or _DEFAULT_EXT[asset_type]
        return "/".join(
            [
                env,
                index,
                doc_id,
                asset_type.value,
                f"page_{page}",
                f"{image_index}.{file_ext}",
            ]
        )

    # ── Generic mode ─────────────────────────────────────────────────
    if page is not None or image_index is not None:
        raise ValueError(
            "`page` and `image_index` require an `asset_type` to be set"
        )

    parts: list[str] = [env, index, doc_id]
    if path is not None:
        parts.append(path)
    return "/".join(parts)


def build_orig_key(
    doc_id: str,
    path: Optional[str] = None,
) -> str:
    """Build an S3 object key for the ORIG bucket.

    The ORIG bucket mirrors the original document path.

    Parameters
    ----------
    doc_id : Unique document identifier (used as key prefix).
    path   : Optional sub-path appended after *doc_id*.

    Returns
    -------
    str – forward-slash-separated S3 key.
    """
    parts: list[str] = [doc_id]
    if path is not None:
        parts.append(path)
    return "/".join(parts)
