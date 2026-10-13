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


def test_h_is_inert_in_all_modes(view, app):
    """(#100) The dead hint-mode key was removed: h does nothing whether
    the search bar is open (viewer focused) or closed."""
    open_search(view, app, "alpha")
    press_return(view.search_bar.search_input, app)  # viewer focused, bar open

    scroll_before = view.pdf_view.verticalScrollBar().value()
    QTest.keyClick(view, Qt.Key.Key_H)
    app.processEvents()
    assert view.pdf_view.verticalScrollBar().value() == scroll_before

    QTest.keyClick(view, Qt.Key.Key_Escape)
    app.processEvents()
    QTest.keyClick(view, Qt.Key.Key_H)
    app.processEvents()
    assert view.pdf_view.verticalScrollBar().value() == scroll_before


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


# ------------------------------------------------------------
# Working Set discard confirm (#107)
# ------------------------------------------------------------


def _press_discard_reply(monkeypatch, button):
    from PyQt6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *a, **k: button),
    )


def test_go_back_cancel_keeps_working_set(view, app, monkeypatch):
    """(#107 AC) Declining the discard prompt leaves the reader open and
    the pending yellow selections intact."""
    from PyQt6.QtWidgets import QMessageBox

    view.working_set = [1, 2]
    backs = []
    view.back_requested.connect(lambda: backs.append(1))
    _press_discard_reply(monkeypatch, QMessageBox.StandardButton.No)

    view.go_back()

    assert backs == [], "cancelled Back must not navigate away"
    assert view.working_set == [1, 2]


def test_go_back_confirm_discards_and_navigates(view, app, monkeypatch):
    """(#107) Accepting the prompt clears the Working Set and emits Back."""
    from PyQt6.QtWidgets import QMessageBox

    view.working_set = [1]
    backs = []
    view.back_requested.connect(lambda: backs.append(1))
    _press_discard_reply(monkeypatch, QMessageBox.StandardButton.Yes)

    view.go_back()

    assert backs == [1]
    assert view.working_set == []


def test_go_back_with_empty_working_set_never_asks(view, app, monkeypatch):
    """(#107) No pending selections → no dialog, Back just works."""
    from PyQt6.QtWidgets import QMessageBox

    view.working_set = []
    backs = []
    view.back_requested.connect(lambda: backs.append(1))
    asked = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *a, **k: asked.append(1) or QMessageBox.StandardButton.Yes),
    )

    view.go_back()

    assert asked == [], "empty Working Set must not prompt"
    assert backs == [1]


class _FakeCloseEvent:
    def __init__(self):
        self.accepted = False
        self.ignored = False

    def accept(self):
        self.accepted = True

    def ignore(self):
        self.ignored = True


def test_close_event_cancel_keeps_working_set(view, app, monkeypatch):
    """(#107) Window close with a non-empty Working Set asks; declining
    cancels the close and keeps the selections."""
    from PyQt6.QtWidgets import QMessageBox

    view.working_set = [1]
    _press_discard_reply(monkeypatch, QMessageBox.StandardButton.No)
    ev = _FakeCloseEvent()

    view.closeEvent(ev)

    assert ev.ignored
    assert view.working_set == [1]


# ------------------------------------------------------------
# Clickable Zoom Fit (#105) and go-to-page (#106)
# ------------------------------------------------------------


def test_zoom_fit_button_restores_fit_width(view, app):
    """(#105 AC) Zooming in then clicking Fit returns to FitToWidth."""
    from PyQt6.QtPdfWidgets import QPdfView

    view.zoom_in()
    assert view.pdf_view.zoomMode() == QPdfView.ZoomMode.Custom

    view.zoom_fit_btn.click()

    assert view.pdf_view.zoomMode() == QPdfView.ZoomMode.FitToWidth
    assert view.zoom_fit_btn.text() == "Zoom: Fit"


def test_zoom_in_label_shows_percentage(view, app):
    """(#105) The Fit button's label reflects the custom zoom level."""
    view.zoom_in()
    assert "%" in view.zoom_fit_btn.text()


def test_zoom_fit_button_text_is_palette_adaptive(view, app):
    """(#105 follow-up) The Fit button and page-total label must follow the
    palette: the toolbar is dark under system dark mode and light under a
    light palette, so ANY hardcoded text color vanishes half the time
    (white was invisible on light, dark on dark). Regression guard."""
    for widget in (view.zoom_fit_btn, view.page_total_label):
        style = widget.styleSheet().lower()
        assert "color:white" not in style, (
            f"{type(widget).__name__} hardcodes white - invisible on a "
            "light palette"
        )
        assert "#2c3e50" not in style, (
            f"{type(widget).__name__} hardcodes dark text - invisible on "
            "the dark (system dark mode) toolbar"
        )
        assert "palette(" in style, (
            f"{type(widget).__name__} should take its color from "
            "palette(...) so it adapts to the theme"
        )


def test_goto_page_input_jumps_and_clamps(view, app):
    """(#106 AC) Typing a page number + Enter jumps; out-of-range values
    clamp to the document; invalid text restores the current page."""
    assert view.doc.pageCount() == 3

    view.page_input.setText("3")
    QTest.keyClick(view.page_input, Qt.Key.Key_Return)
    app.processEvents()
    assert view.last_visible_page == 2
    assert view.page_input.text() == "3"

    view.page_input.setText("99")
    QTest.keyClick(view.page_input, Qt.Key.Key_Return)
    app.processEvents()
    assert view.last_visible_page == 2, "clamped to the last page"

    view.page_input.setText("0")
    QTest.keyClick(view.page_input, Qt.Key.Key_Return)
    app.processEvents()
    assert view.last_visible_page == 0, "clamped to the first page"

    view.page_input.setText("abc")
    QTest.keyClick(view.page_input, Qt.Key.Key_Return)
    app.processEvents()
    assert view.page_input.text() in ("1", "3"), "invalid input restores a page"


# ------------------------------------------------------------
# Errors surface to the user (#102, #103)
# ------------------------------------------------------------


def test_load_failure_shows_warning_dialog(view, app, tmp_path, monkeypatch):
    """(#103 AC) A corrupt/non-PDF file must not leave a blank ghost
    viewer — the user gets a dialog explaining the failure."""
    from PyQt6.QtWidgets import QMessageBox

    fake = tmp_path / "broken.pdf"
    fake.write_text("this is not a pdf")
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warnings.append(a))

    view.load_pdf(str(fake))
    app.processEvents()

    assert warnings, "no warning dialog for a failed load"
    assert view.doc is None


def test_commit_without_db_conn_reports_failure(view, app, monkeypatch):
    """(#102 AC) `e` when the PDF row is gone says so on the Working
    Set label instead of returning silently."""
    monkeypatch.setattr(view, "_db_conn", lambda: None)
    view.working_set = [1]  # non-empty so commit doesn't early-return

    view.commit_working_set()

    assert "Could not save" in view.working_label.text()
    assert view.working_set == [1], "failed commit must keep the Working Set"
