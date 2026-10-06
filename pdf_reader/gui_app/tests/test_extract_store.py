import sqlite3

import pytest

from services.extract_store import (
    IMG_PLACEHOLDER,
    Capture,
    Extract,
    capture_overlaps_extract,
    commit_working_set,
    delete_extract,
    display_title,
    displayed_image_count,
    init_schema,
    list_docs_with_extracts,
    list_extracts_for_doc,
    preview_for_extract,
    resolve_doc_id,
    save_extract_text,
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


def test_fresh_schema_includes_blob_column(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(extracts)").fetchall()}
    assert "text_content" in cols


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

    rows = conn.execute(
        "SELECT id, doc_id, type, text_content FROM extracts"
    ).fetchall()
    assert rows == [(extract_id, doc_id, "text", "hello world")]

    cap = conn.execute(
        "SELECT extract_id, page, rect, kind, text_content, image_blob FROM captures"
    ).fetchone()
    # Captures are anchors: the text lives in the blob, never per-capture.
    assert cap == (extract_id, 0, "10,20,100,40", "text", None, None)


def test_commit_multiple_captures_joins_blob_in_order(conn):
    doc_id = seed_pdf(conn)
    captures = [
        Capture(page=0, rect=(10, 20, 100, 40), kind="text", text_content="first"),
        Capture(page=2, rect=(5, 5, 50, 25), kind="text", text_content="third page"),
    ]
    extract_id = commit_working_set(conn, doc_id, captures)

    blob = conn.execute(
        "SELECT text_content FROM extracts WHERE id = ?", (extract_id,)
    ).fetchone()[0]
    assert blob == "first\n\nthird page"

    caps = conn.execute(
        "SELECT page, rect, kind, text_content FROM captures ORDER BY id"
    ).fetchall()
    assert caps == [
        (0, "10,20,100,40", "text", None),
        (2, "5,5,50,25", "text", None),
    ]


def test_commit_skips_whitespace_text_captures(conn):
    doc_id = seed_pdf(conn)
    captures = [
        Capture(page=0, rect=(0, 0, 1, 1), kind="text", text_content="   \n "),
        Capture(page=1, rect=(2, 2, 3, 3), kind="text", text_content="real"),
    ]
    extract_id = commit_working_set(conn, doc_id, captures)
    blob = conn.execute(
        "SELECT text_content FROM extracts WHERE id = ?", (extract_id,)
    ).fetchone()[0]
    assert blob == "real"


def test_commit_image_capture_stores_blob_and_placeholder(conn):
    doc_id = seed_pdf(conn)
    captures = [Capture(page=1, rect=(0, 0, 10, 10), kind="image", image_blob=b"PNGDATA")]
    extract_id = commit_working_set(conn, doc_id, captures)
    assert (
        conn.execute("SELECT type FROM extracts WHERE id = ?", (extract_id,)).fetchone()[0]
        == "image"
    )
    blob = conn.execute(
        "SELECT text_content FROM extracts WHERE id = ?", (extract_id,)
    ).fetchone()[0]
    assert blob == IMG_PLACEHOLDER
    stored = conn.execute(
        "SELECT image_blob FROM captures WHERE extract_id = ?", (extract_id,)
    ).fetchone()[0]
    assert stored == b"PNGDATA"


def test_image_blob_round_trips_through_list_extracts(conn):
    """An image cap read back via the seam keeps its PNG blob intact."""
    doc_id = seed_pdf(conn)
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 256
    commit_working_set(
        conn,
        doc_id,
        [Capture(page=2, rect=(10, 20, 60, 40), kind="image", image_blob=png)],
    )
    extract = list_extracts_for_doc(conn, doc_id)[0]
    cap = extract.captures[0]
    assert cap.kind == "image"
    assert cap.image_blob == png
    assert cap.page == 2
    assert cap.rect == (10, 20, 60, 40)


def test_commit_mixed_captures_derived_type_combined_and_blob(conn):
    doc_id = seed_pdf(conn)
    captures = [
        Capture(page=0, rect=(10, 20, 100, 40), kind="text", text_content="note"),
        Capture(page=1, rect=(0, 0, 10, 10), kind="image", image_blob=b"PNGDATA"),
    ]
    extract_id = commit_working_set(conn, doc_id, captures)
    row = conn.execute(
        "SELECT type, text_content FROM extracts WHERE id = ?", (extract_id,)
    ).fetchone()
    assert row == ("combined", "note\n\n" + IMG_PLACEHOLDER)


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
    blob = conn.execute(
        "SELECT text_content FROM extracts WHERE id = ?", (extract_id,)
    ).fetchone()[0]
    assert blob == "a\n\nb\n\nc"


def test_list_docs_with_extracts(conn):
    doc_a = seed_pdf(conn, "/tmp/a.pdf", "a.pdf")
    doc_b = seed_pdf(conn, "/tmp/b.pdf", "b.pdf")
    commit_working_set(conn, doc_a, [Capture(0, (0, 0, 1, 1), "text", "x")])

    docs = list_docs_with_extracts(conn)
    assert (doc_a, "a.pdf", "/tmp/a.pdf") in docs
    assert all(d[0] != doc_b for d in docs)


def test_list_docs_with_extracts_survives_pdf_row_removal(conn):
    """Extracts stay listed after the pdfs row is deleted (Q3/r5, #17);
    name/path come back None so the view can mark a removed source."""
    doc_a = seed_pdf(conn, "/tmp/a.pdf", "a.pdf")
    doc_b = seed_pdf(conn, "/tmp/b.pdf", "b.pdf")
    commit_working_set(conn, doc_a, [Capture(0, (0, 0, 1, 1), "text", "a minute")])
    commit_working_set(conn, doc_b, [Capture(0, (0, 0, 1, 1), "text", "gone")])
    conn.execute("DELETE FROM pdfs WHERE id = ?", (doc_b,))
    conn.commit()

    docs = list_docs_with_extracts(conn)
    assert (doc_a, "a.pdf", "/tmp/a.pdf") in docs
    assert (doc_b, None, None) in docs


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
    assert [e.text_content for e in a_extracts] == ["in A"]
    assert [e.text_content for e in b_extracts] == ["in B"]


def test_list_extracts_includes_captures_and_blob(conn):
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
    assert e.text_content == "alpha\n\nbeta"
    assert len(e.captures) == 2
    assert e.captures[0].rect == (0, 0, 1, 1)
    assert e.captures[1].page == 1


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
    assert extracts[0].text_content == "persisted"
    c2.close()


def test_overlap_true_for_rect_inside_capture(conn):
    doc_id = seed_pdf(conn)
    commit_working_set(
        conn, doc_id, [Capture(page=0, rect=(10, 20, 100, 40), kind="text", text_content="x")]
    )
    assert capture_overlaps_extract(conn, doc_id, 0, (20, 25, 30, 35)) is True


def test_overlap_false_for_disjoint_rect(conn):
    doc_id = seed_pdf(conn)
    commit_working_set(
        conn, doc_id, [Capture(page=0, rect=(10, 20, 100, 40), kind="text", text_content="x")]
    )
    assert capture_overlaps_extract(conn, doc_id, 0, (200, 200, 300, 300)) is False


def test_overlap_scoped_to_page(conn):
    doc_id = seed_pdf(conn)
    commit_working_set(
        conn, doc_id, [Capture(page=0, rect=(10, 20, 100, 40), kind="text", text_content="x")]
    )
    # Same rect on a different page must not overlap
    assert capture_overlaps_extract(conn, doc_id, 1, (50, 30, 60, 35)) is False


def test_overlap_scoped_to_doc(conn):
    doc_a = seed_pdf(conn, "/tmp/a.pdf", "a.pdf")
    doc_b = seed_pdf(conn, "/tmp/b.pdf", "b.pdf")
    commit_working_set(
        conn, doc_a, [Capture(page=0, rect=(10, 20, 100, 40), kind="text", text_content="x")]
    )
    assert capture_overlaps_extract(conn, doc_b, 0, (50, 30, 60, 35)) is False


def test_overlap_touching_edge_is_not_overlap(conn):
    doc_id = seed_pdf(conn)
    commit_working_set(
        conn, doc_id, [Capture(page=0, rect=(10, 20, 100, 40), kind="text", text_content="x")]
    )
    # Exactly touching the right edge of the capture: no area shared
    assert capture_overlaps_extract(conn, doc_id, 0, (100, 20, 110, 40)) is False


def test_delete_extract_cascades_captures(conn):
    doc_id = seed_pdf(conn)
    extract_id = commit_working_set(
        conn,
        doc_id,
        [
            Capture(page=0, rect=(10, 20, 100, 40), kind="text", text_content="a"),
            Capture(page=1, rect=(0, 0, 5, 5), kind="image", image_blob=b"PNG"),
        ],
    )
    delete_extract(conn, extract_id)
    assert conn.execute("SELECT COUNT(*) FROM extracts").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM captures").fetchone()[0] == 0
    assert not list_extracts_for_doc(conn, doc_id)


def test_delete_extract_leaves_other_extracts_untouched(conn):
    doc_id = seed_pdf(conn)
    keep = commit_working_set(
        conn, doc_id, [Capture(page=0, rect=(10, 20, 100, 40), kind="text", text_content="keep")]
    )
    gone = commit_working_set(
        conn, doc_id, [Capture(page=1, rect=(5, 5, 50, 50), kind="text", text_content="gone")]
    )
    delete_extract(conn, gone)

    extracts = list_extracts_for_doc(conn, doc_id)
    assert [e.id for e in extracts] == [keep]
    assert extracts[0].text_content == "keep"
    assert conn.execute("SELECT COUNT(*) FROM captures").fetchone()[0] == 1


def test_list_extracts_includes_capture_ids(conn):
    """Captures read back carry their row id (image rows key off it)."""
    doc_id = seed_pdf(conn)
    commit_working_set(
        conn,
        doc_id,
        [
            Capture(page=0, rect=(0, 0, 1, 1), kind="text", text_content="first"),
            Capture(page=1, rect=(2, 2, 3, 3), kind="text", text_content="second"),
        ],
    )
    caps = list_extracts_for_doc(conn, doc_id)[0].captures
    assert all(c.id is not None for c in caps)
    assert caps[0].id != caps[1].id


def test_save_extract_text_replaces_blob_keeps_anchors(conn):
    """One call replaces the whole blob; captures (page/rect/kind/blob)
    are untouched — geometry never changes from an edit."""
    doc_id = seed_pdf(conn)
    extract_id = commit_working_set(
        conn,
        doc_id,
        [
            Capture(page=0, rect=(0, 0, 1, 1), kind="text", text_content="before"),
            Capture(page=1, rect=(2, 2, 3, 3), kind="text", text_content="other"),
        ],
    )

    assert save_extract_text(conn, extract_id, "after\nsecond line") is True

    e = list_extracts_for_doc(conn, doc_id)[0]
    assert e.text_content == "after\nsecond line"
    assert [(c.page, c.rect, c.kind) for c in e.captures] == [
        (0, (0, 0, 1, 1), "text"),
        (1, (2, 2, 3, 3), "text"),
    ]
    stored = conn.execute(
        "SELECT text_content FROM captures WHERE extract_id = ?", (extract_id,)
    ).fetchall()
    assert all(row[0] is None for row in stored)


def test_save_extract_text_allows_empty_blob(conn):
    """Empty and whitespace-only blobs save fine — content and existence
    are independent (the Extract never disappears from a content edit)."""
    doc_id = seed_pdf(conn)
    extract_id = commit_working_set(
        conn,
        doc_id,
        [Capture(page=0, rect=(0, 0, 1, 1), kind="text", text_content="keep me")],
    )

    assert save_extract_text(conn, extract_id, "") is True
    assert save_extract_text(conn, extract_id, "   \n\t ") is True
    assert (
        conn.execute(
            "SELECT text_content FROM extracts WHERE id = ?", (extract_id,)
        ).fetchone()[0]
        == "   \n\t "
    )
    assert [e.id for e in list_extracts_for_doc(conn, doc_id)] == [extract_id]


def test_save_extract_text_all_empty_keeps_extract_and_captures(conn):
    """Emptying the whole blob leaves the Extract row and all Captures."""
    doc_id = seed_pdf(conn)
    extract_id = commit_working_set(
        conn,
        doc_id,
        [
            Capture(page=0, rect=(0, 0, 1, 1), kind="text", text_content="one"),
            Capture(page=1, rect=(2, 2, 3, 3), kind="text", text_content="two"),
        ],
    )

    assert save_extract_text(conn, extract_id, "") is True

    extracts = list_extracts_for_doc(conn, doc_id)
    assert len(extracts) == 1
    assert len(extracts[0].captures) == 2
    assert extracts[0].text_content == ""


def test_save_extract_text_all_empty_with_images_keeps_extract_and_captures(conn):
    """The reported bug (#34): emptying a mixed Extract — all text and
    images deleted — persists as empty; deleted content does not
    resurface on re-open, and the Extract + Capture rows survive."""
    doc_id = seed_pdf(conn)
    extract_id = commit_working_set(
        conn,
        doc_id,
        [
            Capture(page=0, rect=(0, 0, 1, 1), kind="text", text_content="note"),
            Capture(page=1, rect=(2, 2, 3, 3), kind="image", image_blob=b"PNG"),
        ],
    )

    assert save_extract_text(conn, extract_id, "") is True

    extracts = list_extracts_for_doc(conn, doc_id)
    assert len(extracts) == 1
    assert extracts[0].text_content == ""
    assert len(extracts[0].captures) == 2


def test_save_extract_text_leaves_other_extracts_untouched(conn):
    doc_id = seed_pdf(conn)
    keep_id = commit_working_set(
        conn,
        doc_id,
        [Capture(page=0, rect=(0, 0, 1, 1), kind="text", text_content="untouched")],
    )
    edit_id = commit_working_set(
        conn,
        doc_id,
        [Capture(page=1, rect=(9, 9, 10, 10), kind="text", text_content="old")],
    )

    assert save_extract_text(conn, edit_id, "new") is True

    extracts = {e.id: e for e in list_extracts_for_doc(conn, doc_id)}
    assert set(extracts) == {keep_id, edit_id}
    assert extracts[keep_id].text_content == "untouched"
    assert extracts[edit_id].text_content == "new"


def test_save_extract_text_keeps_placeholder_deleted(conn):
    """Deleting an image from the document deletes it from the blob: the
    placeholder is not re-appended (the Capture row stays as the anchor)."""
    doc_id = seed_pdf(conn)
    extract_id = commit_working_set(
        conn,
        doc_id,
        [Capture(page=0, rect=(0, 0, 5, 5), kind="image", image_blob=b"PNG")],
    )

    assert save_extract_text(conn, extract_id, "hello") is True
    e = list_extracts_for_doc(conn, doc_id)[0]
    assert e.text_content == "hello"
    assert e.captures[0].image_blob == b"PNG"

    # Emptying the document stays empty — the image does not resurface.
    assert save_extract_text(conn, extract_id, "") is True
    e = list_extracts_for_doc(conn, doc_id)[0]
    assert e.text_content == ""
    assert len(e.captures) == 1


def test_save_extract_text_strips_extra_placeholders_from_end(conn):
    doc_id = seed_pdf(conn)
    extract_id = commit_working_set(
        conn,
        doc_id,
        [Capture(page=0, rect=(0, 0, 5, 5), kind="image", image_blob=b"PNG")],
    )

    pasted = "a\n\n" + IMG_PLACEHOLDER + "\n\n" + IMG_PLACEHOLDER
    assert save_extract_text(conn, extract_id, pasted) is True
    e = list_extracts_for_doc(conn, doc_id)[0]
    assert e.text_content == "a\n\n" + IMG_PLACEHOLDER


def test_save_extract_text_strips_placeholders_without_images(conn):
    doc_id = seed_pdf(conn)
    extract_id = commit_working_set(
        conn,
        doc_id,
        [Capture(page=0, rect=(0, 0, 1, 1), kind="text", text_content="x")],
    )

    assert save_extract_text(conn, extract_id, "x\n\n" + IMG_PLACEHOLDER) is True
    e = list_extracts_for_doc(conn, doc_id)[0]
    assert e.text_content == "x\n\n"


def test_save_extract_text_unknown_extract_returns_false(conn):
    assert save_extract_text(conn, 9999, "anything") is False


def test_save_extract_text_survives_reopen(conn, tmp_path):
    """A saved blob persists across an app restart (store-seam AC)."""
    doc_id = seed_pdf(conn)
    extract_id = commit_working_set(
        conn,
        doc_id,
        [Capture(page=0, rect=(0, 0, 1, 1), kind="text", text_content="draft")],
    )
    assert save_extract_text(conn, extract_id, "final wording") is True
    conn.close()

    db_path = tmp_path / "test.db"
    c2 = sqlite3.connect(db_path)
    init_schema(c2)
    extracts = list_extracts_for_doc(c2, doc_id)
    assert extracts[0].text_content == "final wording"
    c2.close()


# --- migration from the pre-blob schema -----------------------------------


def _connect(tmp_path, name="mig.db"):
    return sqlite3.connect(tmp_path / name)


def _legacy_schema(conn):
    """Pre-blob schema: extracts without text_content, captures with text."""
    conn.execute(
        """
        CREATE TABLE extracts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            type TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE captures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            extract_id INTEGER NOT NULL REFERENCES extracts(id) ON DELETE CASCADE,
            page INTEGER NOT NULL,
            rect TEXT NOT NULL,
            kind TEXT NOT NULL,
            text_content TEXT,
            image_blob BLOB
        )
        """
    )


def test_migration_backfills_blob_and_nulls_capture_text(tmp_path):
    conn = _connect(tmp_path)
    _legacy_schema(conn)
    cur = conn.execute("INSERT INTO extracts (doc_id, type) VALUES (1, 'combined')")
    eid = cur.lastrowid
    conn.execute(
        "INSERT INTO captures (extract_id, page, rect, kind, text_content)"
        " VALUES (?, 0, '0,0,1,1', 'text', 'first')",
        (eid,),
    )
    conn.execute(
        "INSERT INTO captures (extract_id, page, rect, kind, image_blob)"
        " VALUES (?, 1, '2,2,3,3', 'image', ?)",
        (eid, b"PNG"),
    )
    conn.execute(
        "INSERT INTO captures (extract_id, page, rect, kind, text_content)"
        " VALUES (?, 2, '4,4,5,5', 'text', 'third')",
        (eid,),
    )
    conn.commit()

    init_schema(conn)

    blob = conn.execute(
        "SELECT text_content FROM extracts WHERE id = ?", (eid,)
    ).fetchone()[0]
    assert blob == "first\n\n" + IMG_PLACEHOLDER + "\n\nthird"
    caps = conn.execute(
        "SELECT kind, text_content FROM captures ORDER BY id"
    ).fetchall()
    assert caps == [("text", None), ("image", None), ("text", None)]
    conn.close()


def test_migration_preserves_image_only_and_empty_extracts(tmp_path):
    conn = _connect(tmp_path)
    _legacy_schema(conn)
    cur = conn.execute("INSERT INTO extracts (doc_id, type) VALUES (1, 'image')")
    img_id = cur.lastrowid
    conn.execute(
        "INSERT INTO captures (extract_id, page, rect, kind, image_blob)"
        " VALUES (?, 3, '0,0,1,1', 'image', ?)",
        (img_id, b"PNG"),
    )
    cur = conn.execute("INSERT INTO extracts (doc_id, type) VALUES (1, 'text')")
    empty_id = cur.lastrowid
    conn.commit()

    init_schema(conn)

    rows = dict(
        conn.execute("SELECT id, text_content FROM extracts").fetchall()
    )
    assert rows[img_id] == IMG_PLACEHOLDER
    assert rows[empty_id] == ""
    conn.close()


def test_migration_is_idempotent(tmp_path):
    conn = _connect(tmp_path)
    _legacy_schema(conn)
    conn.execute("INSERT INTO extracts (doc_id, type) VALUES (1, 'text')")
    eid = conn.execute("SELECT id FROM extracts").fetchone()[0]
    conn.execute(
        "INSERT INTO captures (extract_id, page, rect, kind, text_content)"
        " VALUES (?, 0, '0,0,1,1', 'text', 'keep')",
        (eid,),
    )
    conn.commit()

    init_schema(conn)
    init_schema(conn)

    blob = conn.execute(
        "SELECT text_content FROM extracts WHERE id = ?", (eid,)
    ).fetchone()[0]
    assert blob == "keep"
    conn.close()


# --- previews --------------------------------------------------------------


def make_extract(captures, etype="text", extract_id=1, text_content=None):
    return Extract(
        id=extract_id,
        doc_id=1,
        type=etype,
        captures=captures,
        text_content=text_content,
    )


def text_cap(text=None, page=0):
    return Capture(page=page, rect=(0, 0, 1, 1), kind="text", text_content=text)


def image_cap(page=0):
    return Capture(page=page, rect=(0, 0, 1, 1), kind="image", image_blob=b"PNG")


def test_preview_short_text_is_whole_text():
    ex = make_extract([text_cap()], text_content="The mitochondria is the powerhouse")
    assert preview_for_extract(ex) == "The mitochondria is the powerhouse"


def test_preview_truncates_after_60_chars_with_ellipsis():
    long_text = "x" * 61
    ex = make_extract([text_cap()], text_content=long_text)
    preview = preview_for_extract(ex)
    assert len(preview) == 61  # 60 chars + ellipsis
    assert preview.endswith("…")
    assert preview.startswith("x" * 60)


def test_preview_normalizes_whitespace_to_one_line():
    ex = make_extract([text_cap()], text_content="first line\nsecond   line\tends")
    assert preview_for_extract(ex) == "first line second line ends"


def test_preview_uses_first_text_chunk_of_blob():
    ex = make_extract(
        [text_cap(), text_cap(page=1)],
        text_content="first paragraph\n\nsecond paragraph",
    )
    assert preview_for_extract(ex) == "first paragraph"


def test_preview_combined_uses_first_text_not_images():
    """Combined Extract: placeholders are skipped — the preview comes from
    the first text chunk even when images are captured before it."""
    ex = make_extract(
        [image_cap(page=7), text_cap("quoted insight"), image_cap(page=9)],
        etype="combined",
        text_content=IMG_PLACEHOLDER + "\n\nquoted insight\n\n" + IMG_PLACEHOLDER,
    )
    assert preview_for_extract(ex) == "quoted insight"


def test_preview_strips_placeholder_inside_text_chunk():
    """Text typed right next to an image (no blank line) still previews
    cleanly — the placeholder is dropped, words re-joined."""
    ex = make_extract(
        [text_cap(), image_cap()],
        etype="combined",
        text_content="before" + IMG_PLACEHOLDER + "after",
    )
    assert preview_for_extract(ex) == "before after"


def test_preview_image_only_single_page():
    ex = make_extract(
        [image_cap(page=2), image_cap(page=2)],
        etype="image",
        text_content=IMG_PLACEHOLDER + "\n\n" + IMG_PLACEHOLDER,
    )
    assert preview_for_extract(ex) == "p. 3"


def test_preview_image_only_contiguous_page_range():
    ex = make_extract(
        [image_cap(page=3), image_cap(page=4)],
        etype="image",
        text_content=IMG_PLACEHOLDER + "\n\n" + IMG_PLACEHOLDER,
    )
    assert preview_for_extract(ex) == "pp. 4–5"


def test_preview_image_only_non_contiguous_pages_listed():
    ex = make_extract(
        [image_cap(page=0), image_cap(page=4)],
        etype="image",
        text_content=IMG_PLACEHOLDER + "\n\n" + IMG_PLACEHOLDER,
    )
    assert preview_for_extract(ex) == "pp. 1, 5"


def test_preview_page_span_shrinks_when_image_deleted_from_document():
    """(#44) the span covers the images still displayed — a deleted
    placeholder shrinks a multi-page span (anchors stay but count out)."""
    ex = make_extract(
        [image_cap(page=0), image_cap(page=4)],
        etype="image",
        text_content=IMG_PLACEHOLDER,
    )
    assert preview_for_extract(ex) == "p. 1"


def test_preview_same_page_partial_delete_keeps_span():
    """Images sharing a page: partial deletion cannot shrink a page-span
    preview (the remaining image is on the same page) — accepted blur."""
    ex = make_extract(
        [image_cap(page=34), image_cap(page=34)],
        etype="image",
        text_content=IMG_PLACEHOLDER,
    )
    assert preview_for_extract(ex) == "p. 35"


def test_preview_image_only_with_all_images_deleted_is_empty_marker():
    """Images are deletable from the document (#34): a pure image Extract
    whose placeholders are all gone previews (empty) — the Capture
    anchors stay, but nothing is displayed any more."""
    ex = make_extract(
        [image_cap(page=2), image_cap(page=3)],
        etype="image",
        text_content="",
    )
    assert preview_for_extract(ex) == "(empty)"


def test_preview_all_empty_text_without_images_is_empty_marker():
    ex = make_extract([text_cap(), text_cap(page=1)], text_content="   \n\n  ")
    assert preview_for_extract(ex) == "(empty)"


def test_preview_combined_with_emptied_text_is_empty_marker_not_pages():
    """Spec AC: an Extract whose text has been emptied shows (empty) —
    even when image Captures remain (only pure image Extracts show pages)."""
    ex = make_extract(
        [text_cap(), image_cap(page=5), image_cap(page=6)],
        etype="combined",
        text_content=IMG_PLACEHOLDER + "\n\n" + IMG_PLACEHOLDER,
    )
    assert preview_for_extract(ex) == "(empty)"


def test_preview_from_real_store_round_trip(conn):
    """The helper works on Extracts as read back from the store."""
    doc_id = seed_pdf(conn)
    commit_working_set(
        conn,
        doc_id,
        [Capture(page=0, rect=(0, 0, 1, 1), kind="text", text_content="from the db")],
    )
    ex = list_extracts_for_doc(conn, doc_id)[0]
    assert preview_for_extract(ex) == "from the db"


def test_displayed_image_count_full_blob_displays_all():
    ex = make_extract(
        [image_cap(page=1), image_cap(page=2)],
        etype="image",
        text_content=IMG_PLACEHOLDER + "\n\n" + IMG_PLACEHOLDER,
    )
    assert displayed_image_count(ex) == 2


def test_displayed_image_count_deleted_placeholder_stays_deleted():
    """(#34) placeholders are never re-added: a blob saved with one
    placeholder displays only the first image Capture in capture order."""
    ex = make_extract(
        [image_cap(page=1), image_cap(page=2)],
        etype="image",
        text_content=IMG_PLACEHOLDER,
    )
    assert displayed_image_count(ex) == 1


def test_displayed_image_count_emptied_blob_displays_none():
    ex = make_extract(
        [image_cap(page=1), image_cap(page=2)],
        etype="image",
        text_content="",
    )
    assert displayed_image_count(ex) == 0


def test_displayed_image_count_null_blob_displays_none():
    ex = make_extract([image_cap(page=1)], etype="image", text_content=None)
    assert displayed_image_count(ex) == 0


def test_displayed_image_count_never_exceeds_image_captures():
    """Unbacked placeholders are display noise (stripped on save); the
    count can never exceed the image Captures actually available."""
    ex = make_extract(
        [image_cap(page=1)],
        etype="image",
        text_content=IMG_PLACEHOLDER + "\n\n" + IMG_PLACEHOLDER,
    )
    assert displayed_image_count(ex) == 1


def test_displayed_image_count_from_real_store_round_trip(conn):
    """The display rule works on Extracts as read back from the store,
    including after an edit deleted one placeholder."""
    doc_id = seed_pdf(conn)
    eid = commit_working_set(
        conn,
        doc_id,
        [
            Capture(page=0, rect=(0, 0, 1, 1), kind="text", text_content="t"),
            Capture(page=1, rect=(0, 0, 1, 1), kind="image", image_blob=b"\x89PNG"),
            Capture(page=2, rect=(0, 0, 1, 1), kind="image", image_blob=b"\x89PNG"),
        ],
    )
    assert displayed_image_count(list_extracts_for_doc(conn, doc_id)[0]) == 2
    save_extract_text(conn, eid, "t" + "\n\n" + IMG_PLACEHOLDER)
    assert displayed_image_count(list_extracts_for_doc(conn, doc_id)[0]) == 1


def _make_pdf(path, title=None):
    import pymupdf

    doc = pymupdf.open()
    doc.new_page()
    if title is not None:
        doc.set_metadata({"title": title})
    doc.save(str(path))
    doc.close()


def test_display_title_uses_pdf_metadata(tmp_path):
    p = tmp_path / "ugly_v1_file.pdf"
    _make_pdf(p, title="Nice Title")
    assert display_title(str(p), p.name) == "Nice Title"


def test_display_title_falls_back_to_cleaned_filename(tmp_path):
    p = tmp_path / "2020-11-11_v5.0_Supermemo_lore.pdf"
    _make_pdf(p)
    assert display_title(str(p), p.name) == "2020-11-11 v5.0 Supermemo lore"


def test_display_title_missing_file_cleans_name():
    assert display_title(r"Z:\nowhere\missing_file.pdf", "missing_file.pdf") == (
        "missing file"
    )


def test_display_title_whitespace_only_metadata_falls_back(tmp_path):
    p = tmp_path / "plain.pdf"
    _make_pdf(p, title="   ")
    assert display_title(str(p), p.name) == "plain"
