import sqlite3

import pytest

from services.extract_store import (
    Capture,
    commit_working_set,
    init_schema,
    list_docs_with_extracts,
    list_extracts_for_doc,
    resolve_doc_id,
)


@pytest.fixture
def conn(tmp_path):
    c = sqlite3.connect(tmp_path / "test.db")
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS pdfs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            total_pages INTEGER DEFAULT 0,
            current_page INTEGER DEFAULT 1,
            last_opened TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    init_schema(c)
    yield c
    c.close()


def seed_pdf(conn, path="/tmp/book.pdf", name="book.pdf"):
    conn.execute(
        "INSERT INTO pdfs (path, name, total_pages, current_page) VALUES (?, ?, 3, 1)",
        (path, name),
    )
    conn.commit()
    return conn.execute("SELECT id FROM pdfs WHERE path = ?", (path,)).fetchone()[0]


def test_init_schema_creates_tables(conn):
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {"extracts", "captures"} <= tables


def test_commit_empty_working_set_is_noop(conn):
    doc_id = seed_pdf(conn)
    result = commit_working_set(conn, doc_id, [])
    assert result is None
    assert conn.execute("SELECT COUNT(*) FROM extracts").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM captures").fetchone()[0] == 0


def test_commit_single_text_capture(conn):
    doc_id = seed_pdf(conn)
    captures = [
        Capture(page=0, rect=(10, 20, 100, 40), kind="text", text_content="hello world")
    ]
    extract_id = commit_working_set(conn, doc_id, captures)
    assert extract_id is not None

    rows = conn.execute("SELECT id, doc_id, type FROM extracts").fetchall()
    assert rows == [(extract_id, doc_id, "text")]

    cap = conn.execute(
        "SELECT extract_id, page, rect, kind, text_content, image_blob FROM captures"
    ).fetchone()
    assert cap == (extract_id, 0, "10,20,100,40", "text", "hello world", None)


def test_commit_multiple_captures_preserves_order_and_pages(conn):
    doc_id = seed_pdf(conn)
    captures = [
        Capture(page=0, rect=(10, 20, 100, 40), kind="text", text_content="first"),
        Capture(page=2, rect=(5, 5, 50, 25), kind="text", text_content="third page"),
    ]
    extract_id = commit_working_set(conn, doc_id, captures)

    caps = conn.execute(
        "SELECT page, rect, kind, text_content FROM captures ORDER BY id"
    ).fetchall()
    assert caps == [
        (0, "10,20,100,40", "text", "first"),
        (2, "5,5,50,25", "text", "third page"),
    ]


def test_commit_image_capture_stores_blob(conn):
    doc_id = seed_pdf(conn)
    captures = [Capture(page=1, rect=(0, 0, 10, 10), kind="image", image_blob=b"PNGDATA")]
    extract_id = commit_working_set(conn, doc_id, captures)
    assert (
        conn.execute("SELECT type FROM extracts WHERE id = ?", (extract_id,)).fetchone()[0]
        == "image"
    )
    blob = conn.execute(
        "SELECT image_blob FROM captures WHERE extract_id = ?", (extract_id,)
    ).fetchone()[0]
    assert blob == b"PNGDATA"


def test_commit_mixed_captures_derived_type_combined(conn):
    doc_id = seed_pdf(conn)
    captures = [
        Capture(page=0, rect=(10, 20, 100, 40), kind="text", text_content="note"),
        Capture(page=1, rect=(0, 0, 10, 10), kind="image", image_blob=b"PNGDATA"),
    ]
    extract_id = commit_working_set(conn, doc_id, captures)
    assert (
        conn.execute("SELECT type FROM extracts WHERE id = ?", (extract_id,)).fetchone()[0]
        == "combined"
    )


def test_working_set_spanning_pages_commits_together(conn):
    doc_id = seed_pdf(conn)
    captures = [
        Capture(page=0, rect=(1, 1, 2, 2), kind="text", text_content="a"),
        Capture(page=1, rect=(3, 3, 4, 4), kind="text", text_content="b"),
        Capture(page=2, rect=(5, 5, 6, 6), kind="text", text_content="c"),
    ]
    extract_id = commit_working_set(conn, doc_id, captures)
    assert (
        conn.execute("SELECT COUNT(*) FROM extracts WHERE id = ?", (extract_id,)).fetchone()[0]
        == 1
    )
    assert conn.execute(
        "SELECT COUNT(*) FROM captures WHERE extract_id = ?", (extract_id,)
    ).fetchone()[0] == 3


def test_list_docs_with_extracts(conn):
    doc_a = seed_pdf(conn, "/tmp/a.pdf", "a.pdf")
    doc_b = seed_pdf(conn, "/tmp/b.pdf", "b.pdf")
    commit_working_set(conn, doc_a, [Capture(0, (0, 0, 1, 1), "text", "x")])

    docs = list_docs_with_extracts(conn)
    assert doc_a in docs
    assert doc_b not in docs


def test_list_extracts_for_doc_newest_first(conn):
    doc_id = seed_pdf(conn)
    first = commit_working_set(conn, doc_id, [Capture(0, (0, 0, 1, 1), "text", "old")])
    second = commit_working_set(conn, doc_id, [Capture(0, (2, 2, 3, 3), "text", "new")])

    extracts = list_extracts_for_doc(conn, doc_id)
    assert [e.id for e in extracts] == [second, first]


def test_list_extracts_scoped_to_doc(conn):
    doc_a = seed_pdf(conn, "/tmp/a.pdf", "a.pdf")
    doc_b = seed_pdf(conn, "/tmp/b.pdf", "b.pdf")
    commit_working_set(conn, doc_a, [Capture(0, (0, 0, 1, 1), "text", "in A")])
    commit_working_set(conn, doc_b, [Capture(0, (0, 0, 1, 1), "text", "in B")])

    a_extracts = list_extracts_for_doc(conn, doc_a)
    b_extracts = list_extracts_for_doc(conn, doc_b)
    assert [e.captures[0].text_content for e in a_extracts] == ["in A"]
    assert [e.captures[0].text_content for e in b_extracts] == ["in B"]


def test_list_extracts_includes_captures(conn):
    doc_id = seed_pdf(conn)
    extract_id = commit_working_set(
        conn,
        doc_id,
        [
            Capture(page=0, rect=(0, 0, 1, 1), kind="text", text_content="alpha"),
            Capture(page=1, rect=(2, 2, 3, 3), kind="text", text_content="beta"),
        ],
    )
    extracts = list_extracts_for_doc(conn, doc_id)
    assert len(extracts) == 1
    e = extracts[0]
    assert e.id == extract_id
    assert e.type == "text"
    assert len(e.captures) == 2
    assert e.captures[0].rect == (0, 0, 1, 1)
    assert e.captures[1].text_content == "beta"


def test_resolve_doc_id(conn):
    doc_id = seed_pdf(conn, "/tmp/some.pdf", "some.pdf")
    assert resolve_doc_id(conn, "/tmp/some.pdf") == doc_id
    assert resolve_doc_id(conn, "/tmp/missing.pdf") is None


def test_extracts_survive_reopen(conn, tmp_path):
    conn.close()
    db_path = tmp_path / "test.db"

    c1 = sqlite3.connect(db_path)
    init_schema(c1)
    doc_id = seed_pdf(c1, "/tmp/book.pdf", "book.pdf")
    commit_working_set(c1, doc_id, [Capture(0, (0, 0, 1, 1), "text", "persisted")])
    c1.close()

    c2 = sqlite3.connect(db_path)
    init_schema(c2)
    extracts = list_extracts_for_doc(c2, doc_id)
    assert len(extracts) == 1
    assert extracts[0].captures[0].text_content == "persisted"
    c2.close()