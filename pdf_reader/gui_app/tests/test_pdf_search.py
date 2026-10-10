"""Reader search (#75): vim-style search runs only on Enter — fresh every
time, first match highlighted green and centred in view, n/N cycle matches
while the bar is open and revert to page navigation after Esc. Offscreen
widget tests over a small generated fixture PDF."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
import pymupdf
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QTableWidget

from services.pdf_geometry import center_v_scroll
from views.pdf_reader_view import HelpDialog, PDFReaderView


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def fixture_pdf(tmp_path_factory):
    """3-page PDF: 'alpha' twice on page 0 (one near the bottom), once on
    page 2; 'beta' on page 1 — so cycling, wrap and centering are testable."""
    path = tmp_path_factory.mktemp("pdf") / "search_fixture.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "alpha one")
    page.insert_text((72, 700), "alpha two")
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "beta")
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 400), "alpha three")
    doc.save(str(path))
    doc.close()
    return str(path)


@pytest.fixture
def view(app, fixture_pdf):
    v = PDFReaderView()
    v.resize(1000, 800)
    v.show()
    v.activateWindow()
    app.processEvents()
    v.load_pdf(fixture_pdf)
    app.processEvents()
    yield v
    v.hide()


def open_search(view, app, query=None):
    QTest.keyClick(view, Qt.Key.Key_Slash)
    app.processEvents()
    if query is not None:
        view.search_bar.search_input.setText(query)
        app.processEvents()


def press_return(widget, app):
    QTest.keyClick(widget, Qt.Key.Key_Return)
    app.processEvents()


def test_typing_does_not_search_until_enter(view, app):
    open_search(view, app)
    assert view.search_bar.search_input.hasFocus()
    label_before = view.search_bar.match_label.text()
    view.search_bar.search_input.setText("alpha")
    app.processEvents()
    QTest.qWait(350)  # old 250 ms debounce would have fired by now
    assert view.search_matches == []
    assert view.search_bar.match_label.text() == label_before


def test_enter_runs_fresh_search_and_shows_first_match(view, app):
    open_search(view, app, "alpha")
    press_return(view.search_bar.search_input, app)

    assert len(view.search_matches) == 3
    assert view.current_result_index == 0
    match_page, match_rect = view.search_matches[0]
    assert view._search_region[0] == match_page
    assert tuple(view._search_region[1]) == tuple(match_rect)
    assert view.highlight_overlay.current_rect is not None
    assert view.search_bar.match_label.text() == "1/3 matches"
    assert view.hasFocus()


def test_enter_reruns_when_query_changed_no_match_keeps_input(view, app):
    open_search(view, app, "alpha")
    press_return(view.search_bar.search_input, app)
    assert len(view.search_matches) == 3

    inp = view.search_bar.search_input
    inp.setFocus()
    inp.setText("zzz-not-here")
    app.processEvents()
    press_return(inp, app)

    assert view.search_matches == []
    assert view.search_bar.match_label.text() == "No matches"
    assert inp.hasFocus()
    assert inp.selectedText() == "zzz-not-here"
    assert view.highlight_overlay.current_rect is None


def test_enter_with_empty_query_closes_search(view, app):
    open_search(view, app)
    press_return(view.search_bar.search_input, app)
    assert not view.search_bar.isVisible()


def test_enter_on_viewer_cycles_matches_with_wrap(view, app):
    open_search(view, app, "alpha")
    press_return(view.search_bar.search_input, app)
    assert view.current_result_index == 0

    press_return(view, app)
    assert view.current_result_index == 1
    press_return(view, app)
    assert view.current_result_index == 2
    press_return(view, app)
    assert view.current_result_index == 0
    assert view.search_bar.match_label.text() == "1/3 matches"


def test_n_n_cycle_then_page_nav_after_esc(view, app):
    open_search(view, app, "alpha")
    press_return(view.search_bar.search_input, app)
    assert view.current_result_index == 0

    QTest.keyClick(view, Qt.Key.Key_N)
    app.processEvents()
    assert view.current_result_index == 1
    QTest.keyClick(view, Qt.Key.Key_N)
    app.processEvents()
    assert view.current_result_index == 2
    QTest.keyClick(view, Qt.Key.Key_N)
    app.processEvents()
    assert view.current_result_index == 0  # wrap
    QTest.keyClick(view, Qt.Key.Key_N, Qt.KeyboardModifier.ShiftModifier)
    app.processEvents()
    assert view.current_result_index == 2  # wrap backwards
    QTest.keyClick(view, Qt.Key.Key_N)
    app.processEvents()
    assert view.current_result_index == 0  # back on page 0's match

    QTest.keyClick(view, Qt.Key.Key_Escape)
    app.processEvents()
    assert not view.search_bar.isVisible()
    assert view.search_matches == []
    assert view._search_region is None
    assert view.highlight_overlay.current_rect is None

    assert view.pdf_view.pageNavigator().currentPage() == 0
    QTest.keyClick(view, Qt.Key.Key_N)
    app.processEvents()
    assert view.pdf_view.pageNavigator().currentPage() == 1


def test_slash_refocuses_input_when_viewer_focused(view, app):
    open_search(view, app, "alpha")
    press_return(view.search_bar.search_input, app)
    inp = view.search_bar.search_input
    assert not inp.hasFocus()

    QTest.keyClick(view, Qt.Key.Key_Slash)
    app.processEvents()
    assert inp.hasFocus()
    assert inp.hasSelectedText()

    # but '/' typed into an already-focused input stays in the query
    QTest.keyClick(inp, Qt.Key.Key_Slash)
    app.processEvents()
    assert view.search_bar.text().endswith("/")


def test_highlight_rect_tracks_scroll(view, app):
    open_search(view, app, "alpha")
    press_return(view.search_bar.search_input, app)
    rect0 = view.highlight_overlay.current_rect
    assert rect0 is not None

    bar = view.pdf_view.verticalScrollBar()
    before = bar.value()
    bar.setValue(before + 150)
    app.processEvents()

    rect1 = view.highlight_overlay.current_rect
    assert rect1 is not None
    assert rect1.top() == pytest.approx(rect0.top() - 150, abs=1.0)


def test_matches_centred_in_viewport(view, app):
    open_search(view, app, "alpha")
    press_return(view.search_bar.search_input, app)

    # match 0 is centred exactly where center_v_scroll says it should be
    page, rect = view._search_region
    expected = center_v_scroll(view._current_layout(), page, tuple(rect))
    assert view.pdf_view.verticalScrollBar().value() == expected

    # the match low on page 0 must actually be scrolled into view
    low_idx = max(
        (i for i, (p, r) in enumerate(view.search_matches) if p == 0),
        key=lambda i: view.search_matches[i][1].y1,
    )
    while view.current_result_index != low_idx:
        press_return(view, app)
    low_page, low_rect = view._search_region
    expected_low = center_v_scroll(
        view._current_layout(), low_page, tuple(low_rect)
    )
    assert expected_low > 0
    assert view.pdf_view.verticalScrollBar().value() == expected_low

    r = view.highlight_overlay.current_rect
    overlay_h = view.highlight_overlay.height()
    assert 0 <= r.top() and r.bottom() <= overlay_h


def test_h_does_not_trigger_hint_mode_while_search_open(view, app):
    open_search(view, app, "alpha")
    press_return(view.search_bar.search_input, app)  # viewer focused, bar open
    fired = []
    view.hint_mode_requested.connect(lambda: fired.append(1))

    QTest.keyClick(view, Qt.Key.Key_H)
    app.processEvents()
    assert fired == []

    QTest.keyClick(view, Qt.Key.Key_Escape)
    app.processEvents()
    QTest.keyClick(view, Qt.Key.Key_H)
    app.processEvents()
    assert fired == [1]


def test_help_dialog_documents_real_search_flow(app):
    dlg = HelpDialog()
    table = dlg.findChild(QTableWidget)
    assert table is not None
    rows = [
        tuple(table.item(r, c).text() for c in range(3))
        for r in range(table.rowCount())
    ]
    dlg.close()

    enter = [row for row in rows if row[0] == "Enter"]
    assert enter, "Help has no Enter row"
    assert "Run search" in enter[0][2]
    assert "first match" in enter[0][2]

    n_row = next(row for row in rows if row[0] == "n")
    assert "next page" in n_row[2]

    slash = next(row for row in rows if row[0] == "/")
    assert "search" in slash[2].lower()
