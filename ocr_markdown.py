"""Markdown export for OCR conversions.

When OCR runs, Docling nests the text it reads inside a detected picture (a
screenshot pasted into a PDF, a scanned figure, or a whole PNG) under that
picture item, and the default Markdown export drops it, leaving only an
``<!-- image -->`` placeholder. Exporting with ``traverse_pictures=True``
keeps that text.

This module stays free of Docling imports so it can be tested without loading
the conversion engine; the OCR-enabled converters are built in ``core``.
"""

from pathlib import Path
from typing import Any

IMAGE_EXTENSIONS: frozenset[str] = frozenset({".png"})


def document_markdown(document: Any, keep_picture_text: bool) -> str:
    """Export a DoclingDocument, keeping text found inside pictures if asked."""
    if keep_picture_text:
        return document.export_to_markdown(traverse_pictures=True)
    return document.export_to_markdown()


def image_markdown(converter: Any, source_path: Path) -> str:
    """Convert an image with an OCR-enabled converter and export it to Markdown."""
    result = converter.convert(str(source_path))
    return document_markdown(result.document, keep_picture_text=True)
