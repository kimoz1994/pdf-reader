"""Make-flashcard dialog preview tests (#56): the answer view renders
blobs as inline images at the placeholder positions, offscreen."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import QBuffer, QIODevice, QUrl
from PyQt6.QtGui import QImage, QTextDocument, QTextFormat
from PyQt6.QtWidgets import QApplication

from services.extract_store import IMG_PLACEHOLDER
from views.extracts_view import _FlashcardDialog


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _make_png(width, color):
    img = QImage(width, 6, QImage.Format.Format_RGB32)
    img.fill(color)
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    assert img.save(buf, "PNG")
    return bytes(buf.data())


def _fragments(dialog):
    frags = []
    block = dialog.answer_view.document().begin()
    while block.isValid():
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            if frag.isValid():
                frags.append(frag)
            it += 1
        block = block.next()
    return frags


def test_dialog_renders_blob_as_image_not_placeholder(app):
    """(#56 AC) The preview shows the image, not just the box char."""
    blob = _make_png(40, 0x2266CC)
    dlg = _FlashcardDialog(f"See {IMG_PLACEHOLDER} here", [blob])
    frags = _fragments(dlg)
    images = [f for f in frags if f.charFormat().isImageFormat()]
    assert len(images) == 1
    name = images[0].charFormat().property(QTextFormat.Property.ImageName)
    res = dlg.answer_view.document().resource(
        QTextDocument.ResourceType.ImageResource, QUrl(name)
    )
    assert isinstance(res, QImage) and res.width() == 40
    # the visible text keeps its words around the image
    plain = dlg.answer_view.document().toPlainText()
    assert "See" in plain and "here" in plain


def test_dialog_mixed_answer_pairs_every_placeholder(app):
    """(#56 AC) Text + two images: two inline images in order."""
    dlg = _FlashcardDialog(
        f"A{IMG_PLACEHOLDER}B{IMG_PLACEHOLDER}C",
        [_make_png(10, 0xFF0000), _make_png(20, 0x00FF00)],
    )
    images = [f for f in _fragments(dlg) if f.charFormat().isImageFormat()]
    assert len(images) == 2
    assert "A" in dlg.answer_view.document().toPlainText()


def test_dialog_text_only_answer_has_no_images(app):
    dlg = _FlashcardDialog("just words", [])
    assert not any(
        f.charFormat().isImageFormat() for f in _fragments(dlg)
    )
    assert dlg.answer_view.document().toPlainText() == "just words"
