from enum import Enum


class BucketType(Enum):
    """
    Determines which S3 bucket and key-building strategy to use.

    TEMP  – transient processing artefacts; keys are constructed from
            env / index / doc_id (with optional page & item index).
    ORIG  – original ingested documents; keys mirror the source path.
    """

    TEMP = "temp"
    ORIG = "orig"


class AssetType(Enum):
    """
    The kind of extracted asset being stored in the TEMP bucket.

    IMAGE  – raw image bytes extracted from a PDF page.
    TEXT   – OCR text output for a specific extracted image.

    Each asset type gets its own sub-folder in the S3 key hierarchy so
    a single doc_id / page / image_index can have both an image file
    and its corresponding OCR text stored side-by-side:

        {env}/{index}/{doc_id}/image/page_{page}/{image_index}.png
        {env}/{index}/{doc_id}/text/page_{page}/{image_index}.txt
    """

    IMAGE = "image"
    TEXT = "text"
