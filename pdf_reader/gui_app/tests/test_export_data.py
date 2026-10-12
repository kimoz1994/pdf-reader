"""Export seams (#112): CSV for Anki, Markdown for extracts."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sqlite3

from services.extract_store import (
    Capture,
    commit_working_set,
    create_flashcard,
    init_schema,
    list_docs_with_extracts,
    list_extracts_for_doc,
)
from services.export_data import extracts_to_markdown, flashcards_to_csv


def _card(question, answer, source=None, due=None):
    from services.extract_store import Flashcard

    return Flashcard(
        id=1,
        question=question,
        answer_text=answer,
        source_name=source,
        due_utc=due,
    )


def test_csv_has_header_and_rows():
    csv_text = flashcards_to_csv(
        [_card("Q1?", "A1", "book.pdf", "2026-10-12T00:00:00+00:00")]
    )
    lines = csv_text.splitlines()
    assert lines[0] == "Question,Answer,Source,Due"
    assert lines[1].startswith("Q1?,A1,book.pdf,")
    assert len(lines) == 2


def test_csv_quotes_commas_and_newlines():
    csv_text = flashcards_to_csv([_card("Q, with comma", "line1\nline2")])
    # One logical record + header = 3 physical lines (newline is quoted).
    assert csv_text.count("\n") >= 3
    assert '"Q, with comma"' in csv_text
    assert '"line1\nline2"' in csv_text


def test_csv_image_placeholder_and_missing_source():
    csv_text = flashcards_to_csv([_card("Q?", "text\uFFFCmore")])
    assert "[image]" in csv_text
    assert "\uFFFC" not in csv_text
    # Missing source → "-" so the column doesn't collapse.
    assert ",-," in csv_text


def test_markdown_groups_extracts_under_document_headings():
    docs = [(1, "book.pdf", "C:/book.pdf")]
    extract = type(
        "E",
        (),
        {"id": 7, "text_content": "hello\uFFFCworld", "doc_id": 1},
    )()
    md = extracts_to_markdown(docs, {1: [extract]})
    assert md.startswith("# Library exports")
    assert "# book.pdf" in md
    assert "## Extract 7" in md
    assert "hello[image]world" in md
    assert "\uFFFC" not in md


def test_markdown_end_to_end_from_db(tmp_path):
    conn = sqlite3.connect(tmp_path / "t.db")
    conn.execute(
        """
        CREATE TABLE pdfs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            total_pages INTEGER DEFAULT 0,
            current_page INTEGER DEFAULT 1,
            last_opened TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    init_schema(conn)
    conn.execute(
        "INSERT INTO pdfs (path, name) VALUES (?, ?)", ("C:/b.pdf", "b.pdf")
    )
    conn.commit()
    doc_id = conn.execute("SELECT id FROM pdfs").fetchone()[0]
    commit_working_set(conn, doc_id, [Capture(0, (0, 0, 1, 1), "text", "note one")])
    create_flashcard(conn, "Q?", "A", extract_id=None, doc_id=doc_id)

    docs = list_docs_with_extracts(conn)
    by_doc = {d[0]: list_extracts_for_doc(conn, d[0]) for d in docs}
    md = extracts_to_markdown(docs, by_doc)
    assert "# b.pdf" in md
    assert "note one" in md

    from services.extract_store import list_flashcards

    csv_text = flashcards_to_csv(list_flashcards(conn))
    assert "Q?,A," in csv_text
    conn.close()
