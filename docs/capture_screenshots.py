"""Capture real windowed screenshots of the app for HOW_TO_USE.md (#74).

Why this exists: the issue requires REAL windowed captures (offscreen Qt
has no fonts -> `grab()` output shows empty text boxes). This script runs
the app on the real desktop, drives each documented state, grabs the
window, and writes PNGs into docs/images/.

Privacy: `sqlite3.connect` is redirected so every `library.db` open lands
in a temp file - the real library (personal PDF titles) is never read or
written. Demo content uses copies of pdf_reader/pdfs/test.pdf with
synthetic names.

Run (from anywhere, no QT_QPA_PLATFORM):

    <env python> docs/capture_screenshots.py

Then review the PNGs and reference them from HOW_TO_USE.md.
"""
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path

# Windowed on purpose: offscreen renders no text (the whole point of #74).
os.environ.pop("QT_QPA_PLATFORM", None)

REPO = Path(__file__).resolve().parent.parent
GUI_APP = REPO / "pdf_reader" / "gui_app"
TEST_PDF = REPO / "pdf_reader" / "pdfs" / "test.pdf"
OUT_DIR = REPO / "docs" / "images"
TEMP = Path(os.environ.get("TEMP", "."))
DEMO_DB = TEMP / "pdf_reader_screenshots.db"
DEMO_DIR = TEMP / "pdf_reader_screenshots"

# Demo library: copies of the sample PDF under neutral names (no personal
# file titles end up in the public repo).
DEMO_FILES = [
    ("supermemo-guide.pdf", 1),     # current_page 1: reader opens page 1
    ("spaced-repetition.pdf", 47),
    ("evergreen-notes.pdf", 108),
]


def redirect_library_db():
    """Every `...library.db` connect goes to a temp file (#74 privacy)."""
    DEMO_DB.unlink(missing_ok=True)
    real_connect = sqlite3.connect

    def fake_connect(path, *args, **kwargs):
        if str(path).endswith("library.db"):
            return real_connect(DEMO_DB)
        return real_connect(path, *args, **kwargs)

    sqlite3.connect = fake_connect


def make_figure_png() -> bytes:
    """A small chart-like figure for the inline-image captures (#74)."""
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=340, height=200)
    page.draw_rect(pymupdf.Rect(0, 0, 340, 200), color=(0.8, 0.8, 0.85),
                   fill=(0.97, 0.97, 0.99), width=0.5)
    # Axes
    page.draw_line(pymupdf.Point(40, 165), pymupdf.Point(310, 165),
                   color=(0.3, 0.3, 0.3), width=1.2)
    page.draw_line(pymupdf.Point(40, 165), pymupdf.Point(40, 25),
                   color=(0.3, 0.3, 0.3), width=1.2)
    # Decaying "forgetting curve"
    pts = []
    for i in range(40):
        t = i / 39
        x = 40 + t * 270
        y = 25 + (1 - pow(2.718281828, -3.2 * t)) * 140
        pts.append(pymupdf.Point(x, y))
    page.draw_polyline(pts, color=(0.15, 0.45, 0.85), width=2)
    page.insert_text(pymupdf.Point(46, 40), "Recall %", fontsize=11,
                     color=(0.2, 0.2, 0.2))
    page.insert_text(pymupdf.Point(250, 182), "Time", fontsize=11,
                     color=(0.2, 0.2, 0.2))
    blob = page.get_pixmap().tobytes("png")
    doc.close()
    return blob


def find_line(pdf, page_index: int, needle: str):
    """(rect, text) of the full rendered line containing `needle`, in PDF
    points — the demo highlights hug real text instead of invented boxes.
    Returns (None, "") when the line cannot be found."""
    page = pdf[page_index]
    hits = page.search_for(needle)
    if not hits:
        return None, ""
    h = hits[0]
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            lb = line["bbox"]
            if lb[0] < h.x1 and lb[2] > h.x0 and lb[1] < h.y1 and lb[3] > h.y0:
                text = "".join(span["text"] for span in line["spans"])
                return (lb[0] - 2, lb[1] - 2, lb[2] + 2, lb[3] + 2), text
    return (h.x0, h.y0, h.x1, h.y1), needle


def pump(app, secs=0.25):
    end = time.time() + secs
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


def save_shot(widget, name: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / name
    img = widget.grab()
    if not img.save(str(path)):
        raise RuntimeError(f"could not save {path}")
    print(f"[shot] {name}  {img.width()}x{img.height()}")
    return path


def main():
    redirect_library_db()
    sys.path.insert(0, str(GUI_APP))

    from PyQt6.QtCore import QPointF, QTimer
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")

    from main_window import MainWindow
    from services.extract_store import (
        Capture,
        commit_working_set,
        create_flashcard,
        init_schema,
    )

    win = MainWindow()
    win.resize(1360, 900)
    win.show()
    pump(app, 0.5)

    # ---- seed the demo library ------------------------------------------
    import pymupdf

    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(str(TEST_PDF))
    total = doc.page_count
    italic_rect, italic_text = find_line(doc, 0, "Extracts from websites")
    note_rect, _ = find_line(doc, 0, "Epistemic note")
    doc.close()

    conn = win.library_view.conn
    init_schema(conn)  # extracts/captures/flashcards - idempotent
    cur = win.library_view.cursor
    paths = []
    for i, (name, page) in enumerate(DEMO_FILES):
        target = DEMO_DIR / name
        shutil.copyfile(TEST_PDF, target)
        paths.append(str(target))
        cur.execute(
            "INSERT INTO pdfs (path, name, total_pages, current_page, last_opened)"
            " VALUES (?, ?, ?, ?, datetime('now', ?))",
            (str(target), name, total, page, f"-{i * 5} minutes"),
        )
    conn.commit()
    win.library_view.load_library()

    # ---- seed two extracts (one text-only, one with an inline image) ----
    figure = make_figure_png()
    doc_id = cur.execute(
        "SELECT id FROM pdfs WHERE path = ?", (paths[0],)
    ).fetchone()[0]
    eid_text = commit_working_set(conn, doc_id, [
        Capture(page=0, rect=italic_rect or (60, 120, 460, 240), kind="text",
                text_content=italic_text or
                             "Spaced repetition schedules each review for "
                             "the moment recall is about to fail, so every "
                             "repetition costs the least possible effort."),
    ])
    eid_image = commit_working_set(conn, doc_id, [
        Capture(page=1, rect=(70, 150, 420, 360), kind="text",
                text_content="The forgetting curve shows recall probability "
                             "decaying over time; each well-timed review "
                             "flattens it:"),
        Capture(page=1, rect=(70, 370, 410, 570), kind="image",
                image_blob=figure),
    ])

    # ---- 1. Library: rows ticked, count in the Remove button -------------
    win.show_library()
    pump(app, 0.4)
    pl = win.library_view.pdf_list
    for i in (0, 1):
        pl.itemWidget(pl.item(i)).checkbox.setChecked(True)
    pump(app, 0.2)
    save_shot(win, "library.png")

    # untick again so later shots show the idle toolbar
    for i in (0, 1):
        pl.itemWidget(pl.item(i)).checkbox.setChecked(False)

    # ---- 2. Reader: yellow pending highlight ----------------------------
    win.open_pdf(paths[0])
    v = win.pdf_view
    deadline = time.time() + 20
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.03)
        if (v.doc is not None and v.doc.pageCount() > 0
                and v._current_layout() is not None):
            break
    pump(app, 0.8)

    layout = v._current_layout()
    target = note_rect or (60, 95, 430, 210)
    wx0, wy0, wx1, wy1 = layout.pdf_to_widget(0, target)
    v.drag_start = QPointF(wx0, wy0)
    v.drag_current = QPointF(wx1, wy1)
    v.add_drag_selection()
    if not v.working_set:  # fallback: fabricate the pending capture
        v.working_set.append(Capture(
            page=0, rect=target, kind="text",
            text_content="Epistemic note:",
        ))
        v._refresh_highlights()
    pump(app, 0.4)
    save_shot(win, "reader-yellow.png")

    # ---- 3. Reader: same region blue after `e` --------------------------
    v.commit_working_set()
    pump(app, 0.5)
    save_shot(win, "reader-blue.png")

    # ---- 4. Extracts tree: Document -> Extract rows ---------------------
    win.show_extracts()
    ev = win.extracts_view
    pump(app, 0.5)
    ev.tree.expandAll()
    pump(app, 0.3)
    save_shot(win, "extracts-tree.png")

    # ---- 5. Extract Editor with inline image + toolbar ------------------
    assert ev.open_extract(doc_id, eid_image), "editor did not open"
    pump(app, 0.6)
    save_shot(win, "extract-editor.png")

    # ---- 6. Make-flashcard dialog (answer preview + question) -----------
    ed = ev._editor_doc_edit
    cur_sel = ed.textCursor()
    cur_sel.setPosition(0)
    cur_sel.setPosition(min(140, len(ed.toPlainText())),
                        cur_sel.MoveMode.KeepAnchor)
    ed.setTextCursor(cur_sel)

    def fill_and_close():
        dlg = app.activeModalWidget()
        if dlg is None:
            print("[warn] no modal dialog for the flashcard shot")
            return
        dlg.question_edit.setText("How does spaced repetition cut review effort?")
        dlg.answer_view.verticalScrollBar().setValue(0)
        pump(app, 0.3)
        save_shot(dlg, "flashcard-dialog.png")
        dlg.accept()  # also creates the card -> visible in the list shot

    QTimer.singleShot(400, fill_and_close)
    ev._make_flashcard()
    pump(app, 0.5)

    # ---- 7. Flashcards list --------------------------------------------
    create_flashcard(  # a second card so the list has body
        conn,
        question="What does the forgetting curve plot?",
        answer_text="Recall probability against time since the last review.",
        extract_id=eid_text,
        doc_id=doc_id,
    )
    win.show_flashcards()
    pump(app, 0.6)
    save_shot(win, "flashcards-list.png")

    print(f"[done] {len(list(OUT_DIR.glob('*.png')))} PNGs in {OUT_DIR}")
    # Hard exit: skip closeEvent so the user's saved window geometry and
    # sidebar width are not overwritten by this harness.
    os._exit(0)


if __name__ == "__main__":
    main()
