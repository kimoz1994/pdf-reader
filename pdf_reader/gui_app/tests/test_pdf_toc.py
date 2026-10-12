"""PDF outline / TOC side panel (#113): entries from PyMuPDF's
get_toc, click jumps to the page, hidden when the document has no
outline."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf
import pytest
from PyQt6.QtWidgets import QApplication

from views.pdf_reader_view import PDFReaderView


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def toc_pdf(tmp_path_factory):
    """3-page doc with a 2-level outline: Chapter 1 -> p1, Section 1.1 -> p2."""
    path = tmp_path_factory.mktemp("pdf") / "toc.pdf"
    doc = pymupdf.open()
    for i in range(3):
        doc.new_page().insert_text((72, 72), f"page {i + 1}")
    doc.set_toc([
        [1, "Chapter 1", 1],
        [2, "Section 1.1", 2],
        [1, "Chapter 2", 3],
    ])
    doc.save(str(path))
    doc.close()
    return str(path)


@pytest.fixture(scope="module")
def flat_pdf(tmp_path_factory):
    """2-page doc with no outline at all."""
    path = tmp_path_factory.mktemp("pdf") / "flat.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "a")
    doc.new_page().insert_text((72, 72), "b")
    doc.save(str(path))
    doc.close()
    return str(path)


@pytest.fixture
def view(app):
    v = PDFReaderView()
    v.resize(1100, 800)
    v.show()
    app.processEvents()
    yield v
    v.hide()


def _toc_titles(view):
    tree = view.toc_tree
    titles = []
    for i in range(tree.topLevelItemCount()):
        titles.append(tree.topLevelItem(i).text(0))
        for j in range(tree.topLevelItem(i).childCount()):
            titles.append(tree.topLevelItem(i).child(j).text(0))
    return titles


def test_outline_populated_on_open(view, app, toc_pdf):
    """(#113 AC) Opening a document with an outline fills the panel."""
    view.load_pdf(toc_pdf)
    app.processEvents()

    assert view.toc_panel.isVisible() or view.toc_panel.isHidden() is False
    titles = _toc_titles(view)
    assert "Chapter 1" in titles
    assert "Section 1.1" in titles
    assert "Chapter 2" in titles


def test_toc_click_jumps_to_page(view, app, toc_pdf):
    """(#113 AC) Clicking an entry navigates to that page."""
    view.load_pdf(toc_pdf)
    app.processEvents()

    # Click "Chapter 2" (page 3 -> index 2).
    tree = view.toc_tree
    item = None
    for i in range(tree.topLevelItemCount()):
        if tree.topLevelItem(i).text(0) == "Chapter 2":
            item = tree.topLevelItem(i)
            break
    assert item is not None
    tree.setCurrentItem(item)
    tree.itemClicked.emit(item, 0)
    app.processEvents()

    assert view.last_visible_page == 2
    assert view.page_label.text().endswith("/3")


def test_no_outline_hides_panel(view, app, flat_pdf):
    """(#113 AC) A document without an outline: panel hidden, toggle
    disabled — no empty box staring at the user."""
    view.load_pdf(flat_pdf)
    app.processEvents()

    assert view.toc_tree.topLevelItemCount() == 0
    assert view.toc_panel.isHidden()
    assert not view.toc_toggle.isEnabled()


def test_toggle_shows_and_hides_panel(view, app, toc_pdf):
    """(#113) The toolbar toggle collapses/expands the panel."""
    view.load_pdf(toc_pdf)
    app.processEvents()

    view.toc_toggle.setChecked(False)
    assert view.toc_panel.isHidden()
    view.toc_toggle.setChecked(True)
    assert not view.toc_panel.isHidden()


def test_switching_to_flat_doc_hides_panel(view, app, toc_pdf, flat_pdf):
    """(#113) Outline state tracks the loaded document, not the view."""
    view.load_pdf(toc_pdf)
    app.processEvents()
    assert view.toc_toggle.isEnabled()

    view.load_pdf(flat_pdf)
    app.processEvents()

    assert view.toc_panel.isHidden()
    assert not view.toc_toggle.isEnabled()
