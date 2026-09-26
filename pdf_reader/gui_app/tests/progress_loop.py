"""Offscreen regression loop for read-progress restore.

Bug (fixed): load_pdf() cleared the old QPdfDocument before reading the
saved page; setDocument(None) synchronously fired currentPageChanged(0),
whose handler (on_page_changed) persisted current_page=1 to the DB --
so the restore SELECT read the clobbered value and reopened at page 1.
Fix: _loading_document guard suppresses page-change persistence while a
document is being torn down/rebuilt (pdf_reader_view.py).

Replays the user's exact sequence:
  open PDF -> jump to middle page -> back to library -> reopen PDF -> close
and asserts (a) the view lands on the middle page again, (b) the DB
current_page survives the round-trip, (c) closing doesn't clobber it.

Why standalone and not pytest: offscreen Qt probes may crash at teardown
after writing results (AGENTS.md) -- a pytest crash would poison the suite.
Results are written to a JSON file in TEMP before process exit.

Run (from anywhere):
  <env python> progress_loop.py
Read the "ok"/"checks" fields in the printed JSON (also saved to TEMP).
"""
import io
import json
import os
import sqlite3
import sys
from contextlib import redirect_stdout
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HERE = Path(__file__).resolve().parent           # gui_app/tests
GUI_APP = HERE.parent                            # gui_app
TEST_PDF = GUI_APP.parent / "pdfs" / "test.pdf"  # pdf_reader/pdfs/test.pdf
RESULT_PATH = Path(os.environ.get("TEMP", ".")) / "pdf_reader_progress_loop.json"


def main():
    buf = io.StringIO()
    tmp_db = Path(os.environ.get("TEMP", ".")) / "pdf_reader_progress_loop.db"
    tmp_db.unlink(missing_ok=True)

    # Redirect any library.db open to a temp DB -- never touch the real one.
    real_connect = sqlite3.connect

    def fake_connect(path, *args, **kwargs):
        if str(path).endswith("library.db"):
            return real_connect(tmp_db)
        return real_connect(path, *args, **kwargs)

    sqlite3.connect = fake_connect

    sys.path.insert(0, str(GUI_APP))
    from PyQt6.QtCore import QPointF
    from PyQt6.QtWidgets import QApplication

    with redirect_stdout(buf):
        app = QApplication.instance() or QApplication(sys.argv)
        from main_window import MainWindow

        win = MainWindow()
        win.resize(1200, 800)
        win.show()
        app.processEvents()

        import fitz

        doc = fitz.open(str(TEST_PDF))
        total = doc.page_count
        doc.close()
        pdf = str(TEST_PDF)

        cur = win.library_view.cursor
        cur.execute("DELETE FROM pdfs WHERE path = ?", (pdf,))
        cur.execute(
            "INSERT INTO pdfs (path, name, total_pages, current_page) VALUES (?, ?, ?, 1)",
            (pdf, Path(pdf).name, total),
        )
        win.library_view.conn.commit()

        def db_page():
            win.library_view.cursor.execute(
                "SELECT current_page FROM pdfs WHERE path = ?", (pdf,)
            )
            row = win.library_view.cursor.fetchone()
            return row[0] if row else None

        def pump(n=5):
            for _ in range(n):
                app.processEvents()

        # Open fresh (page 1), then scroll to the middle page.
        win.open_pdf(pdf)
        pump()
        page_on_first_open = win.pdf_view.last_visible_page

        mid = max(1, total // 2)
        win.pdf_view.pdf_view.pageNavigator().jump(mid, QPointF(0.0, 0.0), 0.0)
        pump()
        after_scroll_view = win.pdf_view.last_visible_page
        after_scroll_db = db_page()

        win.go_to_library()
        pump()
        in_library_db = db_page()

        # Reopen: the view must restore to mid and the DB must survive.
        win.open_pdf(pdf)
        pump()
        after_reopen_view = win.pdf_view.last_visible_page
        after_reopen_db = db_page()

        win.close()
        pump()

    # Close the app-level conn (if still open) and re-read the file DB:
    # closing at a mid page must not clobber progress either.
    try:
        real_connect(tmp_db).close()
    except Exception:
        pass
    final_db = None
    if tmp_db.exists():
        conn = real_connect(tmp_db)
        try:
            row = conn.execute(
                "SELECT current_page FROM pdfs WHERE path = ?", (pdf,)
            ).fetchone()
            final_db = row[0] if row else None
        finally:
            conn.close()

    result = {
        "pdf": pdf,
        "total_pages": total,
        "target_mid_page_index": mid,
        "page_on_first_open": page_on_first_open,
        "after_scroll": {"view_index": after_scroll_view, "db_page": after_scroll_db},
        "in_library_db": in_library_db,
        "after_reopen": {"view_index": after_reopen_view, "db_page": after_reopen_db},
        "after_close_db": final_db,
        "prints": buf.getvalue(),
        "checks": {
            "scroll_saved_to_db": after_scroll_db == mid + 1,
            "reopen_restores_view": after_reopen_view == mid,
            "reopen_keeps_db": after_reopen_db == mid + 1,
            "close_keeps_db": final_db == mid + 1,
        },
    }
    result["ok"] = all(result["checks"].values())
    RESULT_PATH.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback

        RESULT_PATH.write_text(
            json.dumps({"ok": False, "error": traceback.format_exc()})
        )
        raise
