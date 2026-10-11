"""Scroll-path hotness (#87): highlight refresh must do no layout work when
nothing is drawn, repaint the overlay once per refresh (not four times), set
the Working Set label only on change, and page changes must persist progress
exactly once through the signal — never with a direct sqlite write.
Offscreen widget tests over a small generated fixture PDF."""
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
def fixture_pdf(tmp_path_factory):
    path = tmp_path_factory.mktemp("pdf") / "refresh_fixture.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "one")
    doc.new_page(width=595, height=842)
    doc.save(str(path))
    doc.close()
    return str(path)


@pytest.fixture
def view(app, fixture_pdf):
    v = PDFReaderView()
    v.resize(1000, 800)
    v.show()
    app.processEvents()
    v.load_pdf(fixture_pdf)
    app.processEvents()
    yield v
    v.hide()


def test_empty_refresh_skips_layout_build(view, app):
    """With nothing to draw, _refresh_highlights must not build a PageLayout
    (the O(pages) walk per scroll tick that #87 removed)."""
    view.working_set = []
    view.extract_captures = []
    view._flash_region = None
    view._search_region = None
    view.highlight_overlay.set_rects([(0, 0, 10, 10)], [], None, None)

    def boom():
        raise AssertionError("layout must not be built for an empty refresh")

    view._current_layout = boom
    view._refresh_highlights()  # must not raise
    ov = view.highlight_overlay
    assert ov.working_rects == []
    assert ov.extract_rects == []
    assert ov.flash_rect is None
    assert ov.current_rect is None


def test_empty_refresh_with_stale_overlay_clears_it_once(view, app):
    """A non-empty overlay is cleared in one repaint; a clean overlay is
    left untouched (no repaint churn)."""
    updates = []
    view.highlight_overlay.update = lambda *a, **kw: updates.append(1)

    view.highlight_overlay.set_rects([(0, 0, 5, 5)], [(1, 1, 2, 2)], None, None)
    updates.clear()
    view._refresh_highlights()
    assert len(updates) == 1

    updates.clear()
    view._refresh_highlights()  # already clean -> no update at all
    assert updates == []


def test_refresh_repaints_overlay_exactly_once_with_rects(view, app):
    """Non-empty refresh: one overlay repaint per call, not four (#87)."""
    from services.extract_store import Capture

    view.working_set = [
        Capture(page=0, rect=(10.0, 20.0, 110.0, 40.0), kind="text",
                text_content="one")
    ]
    updates = []
    view.highlight_overlay.update = lambda *a, **kw: updates.append(1)
    view._refresh_highlights()
    assert len(updates) == 1
    assert view.highlight_overlay.working_rects  # actually drew something
    view.working_set = []
    updates.clear()
    view._refresh_highlights()
    assert len(updates) == 1  # clearing also repaints exactly once


def test_working_label_set_only_when_text_changes(view, app):
    sets = []
    real = view.working_label.setText
    view.working_label.setText = lambda t: sets.append(t) or real(t)

    view.working_set = []
    view._refresh_highlights()
    first = len(sets)          # may or may not set, depending on prior text
    view._refresh_highlights()
    assert len(sets) == first  # unchanged text -> no repeat setText

    from services.extract_store import Capture

    view.working_set = [
        Capture(page=0, rect=(10.0, 20.0, 110.0, 40.0), kind="text",
                text_content="one")
    ]
    view._refresh_highlights()
    assert sets and sets[-1].startswith("Working Set: 1")
    before = len(sets)
    view._refresh_highlights()
    assert len(sets) == before  # same count -> no repeat setText


def test_on_page_changed_persists_only_via_signal(view, app):
    """(#87) The reader must not touch sqlite directly on page change —
    one progress_changed emission is the single persistence path."""
    calls = []

    class _Cursor:
        def execute(self, *args):
            calls.append(args)

    class _Conn:
        def commit(self):
            calls.append(("commit",))

    class _LV:
        cursor = _Cursor()
        conn = _Conn()

    class _Win:
        library_view = _LV()

    view.window = lambda: _Win()
    seen = []
    view.progress_changed.connect(lambda path, page: seen.append((path, page)))
    view.current_pdf = "/some/file.pdf"
    view.on_page_changed(1)
    assert seen == [("/some/file.pdf", 2)]
    assert calls == [], "on_page_changed must not execute UPDATE/commit itself"


def test_open_path_loads_extracts_exactly_once(view, app, fixture_pdf):
    """(#88) load_pdf must NOT load extracts — the show path's
    reload_extract_captures does it, so a double-click open runs the
    (N+1, blob-heavy) query once, not twice."""
    calls = []
    real = view._load_extracts_from_db

    def counting():
        calls.append(1)
        real()

    view._load_extracts_from_db = counting
    view.load_pdf(fixture_pdf)
    app.processEvents()
    assert calls == [], "load_pdf must not load extracts (#88)"

    view.reload_extract_captures()
    assert calls == [1], "re-show loads exactly once"
