"""Headless persistence seam for Extracts and Captures.

Owns all SQL for the `extracts` and `captures` tables in `library.db`.
Pure Python + sqlite3, no Qt imports — this is the single testable seam
for the extract workflow. The GUI never touches these tables directly.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class Capture:
    """One snippet inside an Extract: text or image, bound to a page + rect."""

    page: int
    rect: Tuple[float, float, float, float]  # PDF-space x0,y0,x1,y1
    kind: str  # 'text' | 'image'
    text_content: Optional[str] = None  # kind='text'
    image_blob: Optional[bytes] = None  # kind='image', PNG


@dataclass
class Extract:
    """A persisted Working Set, attached to a Document."""

    id: int
    doc_id: int
    type: str  # 'text' | 'image' | 'combined'
    captures: List[Capture] = field(default_factory=list)


def init_schema(conn) -> None:
    """Create the extracts/captures tables idempotently."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS extracts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            type TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS captures (
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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_extracts_doc ON extracts(doc_id)")
    conn.commit()


def _derive_type(captures: List[Capture]) -> str:
    kinds = {c.kind for c in captures}
    if kinds == {"image"}:
        return "image"
    if kinds == {"text"}:
        return "text"
    return "combined"


def _rect_to_str(rect: Tuple[float, float, float, float]) -> str:
    return ",".join(str(v) for v in rect)


def _rect_from_str(s: str) -> Tuple[float, float, float, float]:
    return tuple(float(v) for v in s.split(","))


def commit_working_set(conn, doc_id: int, captures: List[Capture]) -> Optional[int]:
    """Persist one Working Set as a single Extract. Returns its id, or None if empty."""
    if not captures:
        return None

    cur = conn.execute(
        "INSERT INTO extracts (doc_id, type) VALUES (?, ?)",
        (doc_id, _derive_type(captures)),
    )
    extract_id = cur.lastrowid

    for cap in captures:
        conn.execute(
            """
            INSERT INTO captures (extract_id, page, rect, kind, text_content, image_blob)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                extract_id,
                cap.page,
                _rect_to_str(cap.rect),
                cap.kind,
                cap.text_content,
                cap.image_blob,
            ),
        )
    conn.commit()
    return extract_id


def resolve_doc_id(conn, pdf_path: str) -> Optional[int]:
    """Resolve a PDF path to its Document id in the pdfs table."""
    row = conn.execute("SELECT id FROM pdfs WHERE path = ?", (pdf_path,)).fetchone()
    return row[0] if row else None


def list_extracts_for_doc(conn, doc_id: int) -> List[Extract]:
    """All Extracts for a Document, newest-first, with their Captures."""
    extract_rows = conn.execute(
        """
        SELECT id, doc_id, type FROM extracts
        WHERE doc_id = ?
        ORDER BY id DESC
        """,
        (doc_id,),
    ).fetchall()

    extracts = []
    for eid, edoc, etype in extract_rows:
        cap_rows = conn.execute(
            """
            SELECT page, rect, kind, text_content, image_blob FROM captures
            WHERE extract_id = ?
            ORDER BY id ASC
            """,
            (eid,),
        ).fetchall()
        captures = [
            Capture(
                page=page,
                rect=_rect_from_str(rect),
                kind=kind,
                text_content=text_content,
                image_blob=image_blob,
            )
            for page, rect, kind, text_content, image_blob in cap_rows
        ]
        extracts.append(Extract(id=eid, doc_id=edoc, type=etype, captures=captures))
    return extracts


def list_docs_with_extracts(conn) -> List[Tuple[int, str, str]]:
    """(doc_id, name, path) for Documents that have at least one Extract.

    The pdfs join means a Document whose row has been removed (e.g. the PDF
    was deleted from the library) no longer appears here — matching the
    library's own "exists on disk" behaviour, by design.
    """
    rows = conn.execute(
        """
        SELECT DISTINCT e.doc_id, p.name, p.path
        FROM extracts e
        JOIN pdfs p ON p.id = e.doc_id
        ORDER BY e.doc_id
        """
    ).fetchall()
    return [(r[0], r[1], r[2]) for r in rows]


def capture_overlaps_extract(
    conn, doc_id: int, page: int, rect: Tuple[float, float, float, float]
) -> bool:
    """True if any Extract Capture of `doc_id` overlaps `rect` on `page`.

    Overlap means the rectangles share a non-zero area (touching edges do not
    count). Scoped to the given document and page.
    """
    x0, y0, x1, y1 = rect
    rows = conn.execute(
        """
        SELECT rect FROM captures
        WHERE extract_id IN (
            SELECT id FROM extracts WHERE doc_id = ?
        )
        AND page = ?
        """,
        (doc_id, page),
    ).fetchall()
    for (rect_str,) in rows:
        cx0, cy0, cx1, cy1 = _rect_from_str(rect_str)
        if x0 < cx1 and cx0 < x1 and y0 < cy1 and cy0 < y1:
            return True
    return False


def delete_extract(conn, extract_id: int) -> None:
    """Delete an Extract and all of its Captures (irreversible).

    Uses the FK cascade for captures — the schema declares
    `ON DELETE CASCADE` — but the caller must have foreign-key support
    enabled on the connection for that rule to fire. To stay safe either
    way, captures are removed explicitly in the same transaction.
    """
    conn.execute("DELETE FROM captures WHERE extract_id = ?", (extract_id,))
    conn.execute("DELETE FROM extracts WHERE id = ?", (extract_id,))
    conn.commit()