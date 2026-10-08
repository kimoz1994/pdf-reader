"""Snapshot seam for flashcard creation (#54/#55).

Turns a text selection inside the Extract Editor into an immutable
answer snapshot: the selected plain text (images marked with the object
replacement character U+FFFC, the same character the Extract blob uses)
plus one PNG blob per image, in selection order. No widget is required —
only a QTextDocument and a QTextCursor carrying a selection — so the
logic is fully testable offscreen.
"""
from typing import List, Optional, Tuple

from PyQt6.QtCore import QBuffer, QIODevice, QUrl
from PyQt6.QtGui import (
    QImage,
    QTextBlock,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
)

from .extract_store import IMG_PLACEHOLDER


def snapshot_selection(
    document: QTextDocument, cursor: QTextCursor
) -> Tuple[str, List[bytes]]:
    """The selection's (answer_text, image blobs); ("", []) when empty.

    Blocks are joined with "\\n" (the plain-text form, matching
    QTextDocument.toPlainText()). Every image inside the selection
    contributes one U+FFFC placeholder and exactly one PNG blob —
    placeholders and blobs always come in pairs (#56); an image whose
    resource cannot be re-encoded is skipped entirely. Characters
    outside the selection are never included.
    """
    start = cursor.selectionStart()
    end = cursor.selectionEnd()
    if start >= end:
        return "", []

    chunks: List[str] = []
    blobs: List[bytes] = []
    block = document.begin()
    while block.isValid():
        block_start = block.position()
        # block.length() includes the trailing block separator, which the
        # selection counts in its positions too.
        overlap_start = max(start, block_start)
        overlap_end = min(end, block_start + block.length())
        if overlap_start < overlap_end:
            text, block_blobs = _snapshot_block(
                document, block, overlap_start, overlap_end
            )
            chunks.append(text)
            blobs.extend(block_blobs)
        block = block.next()
    return "\n".join(chunks), blobs


def _snapshot_block(
    document: QTextDocument, block: QTextBlock, overlap_start: int, overlap_end: int
) -> Tuple[str, List[bytes]]:
    """Text and blobs for the block's fragments clipped to the overlap."""
    parts: List[str] = []
    blobs: List[bytes] = []
    it = block.begin()
    while not it.atEnd():
        frag = it.fragment()
        if frag.isValid():
            frag_start = frag.position()
            frag_end = frag_start + frag.length()
            if frag_start < overlap_end and overlap_start < frag_end:
                if frag.charFormat().isImageFormat():
                    blob = _image_blob(document, frag.charFormat())
                    if blob is not None:
                        parts.append(IMG_PLACEHOLDER)
                        blobs.append(blob)
                else:
                    lo = max(overlap_start, frag_start) - frag_start
                    hi = min(overlap_end, frag_end) - frag_start
                    parts.append(frag.text()[lo:hi])
        it += 1
    return "".join(parts), blobs


def _image_blob(
    document: QTextDocument, char_format: QTextCharFormat
) -> Optional[bytes]:
    """The image an image fragment points at, re-encoded as PNG.

    The URL lives in the format's image-name property; the resource is
    the QImage the editor renders (possibly the display-scaled copy),
    exactly what the reader of the snapshot sees.
    """
    name = char_format.property(QTextFormat.Property.ImageName)
    if not isinstance(name, str) or not name:
        return None
    image = document.resource(QTextDocument.ResourceType.ImageResource, QUrl(name))
    if not isinstance(image, QImage) or image.isNull():
        return None
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buf, "PNG"):
        return None
    return bytes(buf.data())
