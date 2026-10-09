"""Snapshot seam tests (#55): a selection inside a QTextDocument ->
(answer_text with U+FFFC, image blobs), no UI required."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import QBuffer, QIODevice, QUrl
from PyQt6.QtGui import QImage, QTextCursor, QTextDocument, QTextImageFormat
from PyQt6.QtWidgets import QApplication

from services.extract_store import IMG_PLACEHOLDER
from services.selection_snapshot import snapshot_image, snapshot_selection


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _make_png(width, height, color):
    img = QImage(width, height, QImage.Format.Format_RGB32)
    img.fill(color)
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    assert img.save(buf, "PNG")
    return bytes(buf.data())


def _select(cursor, start, end):
    cursor.setPosition(start)
    cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
    return cursor


def test_empty_selection_returns_no_snapshot(app):
    doc = QTextDocument()
    doc.setPlainText("hello")
    cur = _select(QTextCursor(doc), 2, 2)
    assert snapshot_selection(doc, cur) == ("", [])


def test_text_selection_is_exact_substring(app):
    doc = QTextDocument()
    doc.setPlainText("hello world")
    cur = _select(QTextCursor(doc), 6, 11)
    assert snapshot_selection(doc, cur) == ("world", [])


def test_multiline_selection_keeps_block_break(app):
    doc = QTextDocument()
    doc.setPlainText("line one\nline two")
    cur = _select(QTextCursor(doc), 0, doc.characterCount() - 1)
    text, blobs = snapshot_selection(doc, cur)
    assert text == "line one\nline two"
    assert blobs == []


def _doc_with_two_images(app):
    """A(0) img0(1) B(2) img1(3) C(4) — charCount 6 (final separator)."""
    doc = QTextDocument()
    cur = QTextCursor(doc)
    cur.insertText("A")
    for i, (w, h) in enumerate(((4, 6), (8, 8))):
        url = f"img://{i}"
        img = QImage(w, h, QImage.Format.Format_RGB32)
        img.fill(0xFF0000)
        doc.addResource(QTextDocument.ResourceType.ImageResource, QUrl(url), img)
        fmt = QTextImageFormat()
        fmt.setName(url)
        cur.insertImage(fmt)
        cur.insertText("BC"[i])
    return doc


def test_full_selection_pairs_placeholders_with_blobs(app):
    doc = _doc_with_two_images(app)
    cur = _select(QTextCursor(doc), 0, doc.characterCount() - 1)

    text, blobs = snapshot_selection(doc, cur)

    assert text == f"A{IMG_PLACEHOLDER}B{IMG_PLACEHOLDER}C"
    assert len(blobs) == 2
    first, second = (QImage.fromData(b) for b in blobs)
    for blob in blobs:
        assert blob[:4] == b"\x89PNG"
    assert not first.isNull() and first.width() == 4
    assert not second.isNull() and second.width() == 8


def test_selection_covering_one_image_keeps_only_it(app):
    doc = _doc_with_two_images(app)
    # A + img0
    text, blobs = snapshot_selection(doc, _select(QTextCursor(doc), 0, 2))
    assert text == f"A{IMG_PLACEHOLDER}"
    assert len(blobs) == 1
    assert QImage.fromData(blobs[0]).width() == 4

    # img1 + C
    text, blobs = snapshot_selection(doc, _select(QTextCursor(doc), 3, 5))
    assert text == f"{IMG_PLACEHOLDER}C"
    assert len(blobs) == 1
    assert QImage.fromData(blobs[0]).width() == 8


def test_selection_without_image_has_no_placeholders_or_blobs(app):
    doc = _doc_with_two_images(app)
    # only "B" (position 2..3)
    assert snapshot_selection(doc, _select(QTextCursor(doc), 2, 3)) == ("B", [])


def test_snapshot_image_by_url_returns_placeholder_and_blob(app):
    """(#56) Image-alone flashcard: one URL in, one U+FFFC + one PNG out."""
    doc = _doc_with_two_images(app)
    text, blobs = snapshot_image(doc, "img://0")
    assert text == IMG_PLACEHOLDER
    assert len(blobs) == 1
    assert QImage.fromData(blobs[0]).width() == 4


def test_snapshot_image_unknown_url_is_empty(app):
    doc = _doc_with_two_images(app)
    assert snapshot_image(doc, "img://missing") == ("", [])
