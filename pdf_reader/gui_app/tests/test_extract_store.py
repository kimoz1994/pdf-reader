import sqlite3

import pytest

from services.extract_store import (
    Capture,
    Extract,
    capture_overlaps_extract,
    commit_working_set,
    delete_extract,
    display_title,
    init_schema,
    list_docs_with_extracts,
    list_extracts_for_doc,
    preview_for_extract,
    resolve_doc_id,
    update_capture_text,
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


def first_capture_id(conn, kind="text"):
    row = conn.execute(
        "SELECT id FROM captures WHERE kind = ? ORDER BY id", (kind,)
    ).fetchone()
    return row[0] if row else None


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
    assert (doc_a, "a.pdf", "/tmp/a.pdf") in docs
    assert all(d[0] != doc_b for d in docs)


def test_list_docs_with_extracts_only_when_pdf_row_exists(conn):
    """A cap with no library row (PDF removed) is hidden, per design."""
    doc_a = seed_pdf(conn, "/tmp/a.pdf", "a.pdf")
    doc_b = seed_pdf(conn, "/tmp/b.pdf", "b.pdf")
    commit_working_set(conn, doc_a, [Capture(0, (0, 0, 1, 1), "text", "a minute")])
    commit_working_set(conn, doc_b, [Capture(0, (0, 0, 1, 1), "text", "gone")])
    conn.execute("DELETE FROM pdfs WHERE id = ?", (doc_b,))
    conn.commit()

    docs = list_docs_with_extracts(conn)
    assert [d[0] for d in docs] == [doc_a]


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
    assert extracts[0].captures[0].text_content == "keep"
    assert conn.execute("SELECT COUNT(*) FROM captures").fetchone()[0] == 1


def test_list_extracts_includes_capture_ids(conn):
    """Captures read back carry their row id (needed for in-place edits)."""
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


def test_update_capture_text_replaces_text(conn):
    doc_id = seed_pdf(conn)
    extract_id = commit_working_set(
        conn,
        doc_id,
        [
            Capture(page=0, rect=(0, 0, 1, 1), kind="text", text_content="before"),
            Capture(page=1, rect=(2, 2, 3, 3), kind="text", text_content="other"),
        ],
    )
    cap_id = first_capture_id(conn)

    assert update_capture_text(conn, cap_id, "after") is True

    extracts = list_extracts_for_doc(conn, doc_id)
    assert extracts[0].id == extract_id
    assert extracts[0].captures[0].text_content == "after"
    assert extracts[0].captures[1].text_content == "other"
    # Geometry untouched: only text_content changes
    assert extracts[0].captures[0].rect == (0, 0, 1, 1)


def test_update_capture_text_rejects_empty_and_whitespace(conn):
    """A trimmed-empty edit is rejected and leaves stored text untouched."""
    doc_id = seed_pdf(conn)
    commit_working_set(
        conn, doc_id, [Capture(page=0, rect=(0, 0, 1, 1), kind="text", text_content="keep me")]
    )
    cap_id = first_capture_id(conn)

    assert update_capture_text(conn, cap_id, "") is False
    assert update_capture_text(conn, cap_id, "   \n\t ") is False
    assert (
        conn.execute(
            "SELECT text_content FROM captures WHERE id = ?", (cap_id,)
        ).fetchone()[0]
        == "keep me"
    )


def test_update_capture_text_rejects_image_capture(conn):
    """Image Captures have no editable text — store refuses even with an id."""
    doc_id = seed_pdf(conn)
    commit_working_set(
        conn, doc_id, [Capture(page=0, rect=(0, 0, 5, 5), kind="image", image_blob=b"PNG")]
    )
    cap_id = first_capture_id(conn, kind="image")

    assert update_capture_text(conn, cap_id, "not allowed") is False
    row = conn.execute(
        "SELECT text_content, image_blob FROM captures WHERE id = ?", (cap_id,)
    ).fetchone()
    assert row == (None, b"PNG")


def test_update_capture_text_unknown_id_returns_false(conn):
    assert update_capture_text(conn, 9999, "anything") is False


def test_updated_text_survives_reopen(conn, tmp_path):
    """The edited text persists across an app restart (store-seam AC)."""
    doc_id = seed_pdf(conn)
    commit_working_set(
        conn, doc_id, [Capture(page=0, rect=(0, 0, 1, 1), kind="text", text_content="draft")]
    )
    cap_id = first_capture_id(conn)
    assert update_capture_text(conn, cap_id, "final wording") is True
    conn.close()

    db_path = tmp_path / "test.db"
    c2 = sqlite3.connect(db_path)
    init_schema(c2)
    extracts = list_extracts_for_doc(c2, doc_id)
    assert extracts[0].captures[0].text_content == "final wording"
    c2.close()


def make_extract(captures, etype="text", extract_id=1):
    return Extract(id=extract_id, doc_id=1, type=etype, captures=captures)


def text_cap(text, page=0):
    return Capture(page=page, rect=(0, 0, 1, 1), kind="text", text_content=text)


def image_cap(page=0):
    return Capture(page=page, rect=(0, 0, 1, 1), kind="image", image_blob=b"PNG")


def test_preview_short_text_is_whole_text():
    ex = make_extract([text_cap("The mitochondria is the powerhouse")])
    assert preview_for_extract(ex) == "The mitochondria is the powerhouse"


def test_preview_truncates_after_60_chars_with_ellipsis():
    long_text = "x" * 61
    ex = make_extract([text_cap(long_text)])
    preview = preview_for_extract(ex)
    assert len(preview) == 61  # 60 chars + ellipsis
    assert preview.endswith("…")
    assert preview.startswith("x" * 60)


def test_preview_normalizes_whitespace_to_one_line():
    ex = make_extract([text_cap("first line\nsecond   line\tends")])
    assert preview_for_extract(ex) == "first line second line ends"


def test_preview_combined_uses_first_text_not_images():
    """Combined Extract: preview comes from the first text Capture, even
    when images are captured before it."""
    ex = make_extract(
        [image_cap(page=7), text_cap("quoted insight"), image_cap(page=9)],
        etype="combined",
    )
    assert preview_for_extract(ex) == "quoted insight"


def test_preview_image_only_single_page():
    ex = make_extract([image_cap(page=2), image_cap(page=2)], etype="image")
    assert preview_for_extract(ex) == "p. 3"


def test_preview_image_only_contiguous_page_range():
    ex = make_extract([image_cap(page=3), image_cap(page=4)], etype="image")
    assert preview_for_extract(ex) == "pp. 4–5"


def test_preview_image_only_non_contiguous_pages_listed():
    ex = make_extract([image_cap(page=0), image_cap(page=4)], etype="image")
    assert preview_for_extract(ex) == "pp. 1, 5"


def test_preview_all_empty_text_without_images_is_empty_marker():
    ex = make_extract([text_cap("   "), text_cap("")])
    assert preview_for_extract(ex) == "(empty)"


def test_preview_combined_with_emptied_text_is_empty_marker_not_pages():
    """Spec AC: an Extract whose text has been emptied shows (empty) —
    even when image Captures remain (only pure image Extracts show pages)."""
    ex = make_extract(
        [text_cap(""), image_cap(page=5), image_cap(page=6)],
        etype="combined",
    )
    assert preview_for_extract(ex) == "(empty)"


def test_preview_skips_empty_text_and_uses_next_nonempty():
    ex = make_extract([text_cap(""), text_cap("second capture speaks")])
    assert preview_for_extract(ex) == "second capture speaks"


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