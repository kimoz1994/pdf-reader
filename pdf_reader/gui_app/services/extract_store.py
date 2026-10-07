"""Headless persistence seam for Extracts and Captures.

Owns all SQL for the `extracts` and `captures` tables in `library.db`.
Pure Python + sqlite3, no Qt imports — this is the single testable seam
for the extract workflow. The GUI never touches these tables directly.

Text model: an Extract's text lives in one blob (`extracts.text_content`).
Captures are immutable anchors (page + rect + kind + image blob) used for
blue re-draw and Jump; per-capture text is never stored. Inline images are
marked in the blob with the object-replacement character (U+FFFC), one per
image Capture in capture order — the same character Qt uses, so editor
round-trips are lossless.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple
import os

# Marks where an inline image sits inside the text blob. One per image
# Capture, in capture order; count is normalized on every save.
IMG_PLACEHOLDER = "\uFFFC"

_BLOB_SEP = "\n\n"


@dataclass
class Capture:
    """One snippet inside an Extract: text or image, bound to a page + rect."""

    page: Optional[int]  # None: pasted image, not from the PDF (#48)
    rect: Optional[Tuple[float, float, float, float]]  # PDF-space
    # x0,y0,x1,y1; None for pasted images (#48)
    kind: str  # 'text' | 'image'
    text_content: Optional[str] = None  # kind='text'
    image_blob: Optional[bytes] = None  # kind='image', PNG
    id: Optional[int] = None  # DB row id (set when read back from the store)
    display_w: Optional[int] = None  # presentation width in px (NULL = auto
    # band #46); page/rect geometry anchors stay immutable (#37)


@dataclass
class Extract:
    """A persisted Working Set, attached to a Document."""

    id: int
    doc_id: int
    type: str  # 'text' | 'image' | 'combined'
    captures: List[Capture] = field(default_factory=list)
    text_content: Optional[str] = None  # the whole-Extract text blob


def init_schema(conn) -> None:
    """Create the extracts/captures tables idempotently.

    Also migrates old databases once: adds `extracts.text_content`
    (pre-blob backfill: per-capture text joined in capture-id order,
    images as placeholders, then the per-capture text NULLed — captures
    are anchors from here on), adds `captures.display_w` (nullable
    presentation width, #37), relaxes page/rect to nullable for pasted
    images (#48, atomic table rewrite), and adds/backfills
    `captures.display_order` (render order, #48). Idempotent via
    column-existence checks.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS extracts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            type TEXT NOT NULL,
            text_content TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS captures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            extract_id INTEGER NOT NULL REFERENCES extracts(id) ON DELETE CASCADE,
            page INTEGER,
            rect TEXT,
            kind TEXT NOT NULL,
            text_content TEXT,
            image_blob BLOB,
            display_w INTEGER,
            display_order INTEGER
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_extracts_doc ON extracts(doc_id)")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(extracts)").fetchall()}
    if "text_content" not in cols:
        conn.execute("ALTER TABLE extracts ADD COLUMN text_content TEXT")
        for (eid,) in conn.execute("SELECT id FROM extracts").fetchall():
            caps = conn.execute(
                "SELECT kind, text_content FROM captures WHERE extract_id = ? ORDER BY id",
                (eid,),
            ).fetchall()
            elements = [
                cap_text if kind == "text" else IMG_PLACEHOLDER
                for kind, cap_text in caps
                if kind == "image" or (cap_text and cap_text.strip())
            ]
            conn.execute(
                "UPDATE extracts SET text_content = ? WHERE id = ?",
                (_BLOB_SEP.join(elements), eid),
            )
        conn.execute("UPDATE captures SET text_content = NULL WHERE kind = 'text'")
    cap_rows = conn.execute("PRAGMA table_info(captures)").fetchall()
    cap_cols = {r[1]: r for r in cap_rows}
    if "page" in cap_cols and "rect" in cap_cols and (
        cap_cols["page"][3] or cap_cols["rect"][3]
    ):
        # page/rect become nullable so pasted images (no PDF anchor) fit
        # (#48). SQLite cannot drop NOT NULL in place — atomic rewrite.
        keep = [
            name
            for name in (
                "id", "extract_id", "page", "rect", "kind",
                "text_content", "image_blob", "display_w", "display_order",
            )
            if name in cap_cols
        ]
        conn.execute(
            """
            CREATE TABLE captures_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                extract_id INTEGER NOT NULL REFERENCES extracts(id) ON DELETE CASCADE,
                page INTEGER,
                rect TEXT,
                kind TEXT NOT NULL,
                text_content TEXT,
                image_blob BLOB,
                display_w INTEGER,
                display_order INTEGER
            )
            """
        )
        conn.execute(
            "INSERT INTO captures_new ({0}) SELECT {0} FROM captures".format(
                ", ".join(keep)
            )
        )
        conn.execute("DROP TABLE captures")
        conn.execute("ALTER TABLE captures_new RENAME TO captures")
        cap_rows = conn.execute("PRAGMA table_info(captures)").fetchall()
        cap_cols = {r[1]: r for r in cap_rows}
    if "display_w" not in cap_cols:
        conn.execute("ALTER TABLE captures ADD COLUMN display_w INTEGER")
    if "display_order" not in cap_cols:
        conn.execute("ALTER TABLE captures ADD COLUMN display_order INTEGER")
    # Backfill display_order for legacy rows: per-extract id order —
    # the exact order the editor rendered images in before #48.
    conn.execute(
        """
        UPDATE captures SET display_order = (
            SELECT COUNT(*) FROM captures c2
            WHERE c2.extract_id = captures.extract_id
              AND c2.id <= captures.id
        ) - 1
        WHERE display_order IS NULL
        """
    )
    conn.commit()


def _derive_type(captures: List[Capture]) -> str:
    kinds = {c.kind for c in captures}
    if kinds == {"image"}:
        return "image"
    if kinds == {"text"}:
        return "text"
    return "combined"


def _rect_to_str(rect: Optional[Tuple[float, float, float, float]]) -> Optional[str]:
    if rect is None:
        return None  # pasted image: no PDF anchor (#48)
    return ",".join(str(v) for v in rect)


def _rect_from_str(s: Optional[str]) -> Optional[Tuple[float, float, float, float]]:
    if not s:
        return None  # pasted image: no PDF anchor (#48)
    return tuple(float(v) for v in s.split(","))


def commit_working_set(conn, doc_id: int, captures: List[Capture]) -> Optional[int]:
    """Persist one Working Set as a single Extract. Returns its id, or None if empty.

    The Extract's text blob joins the captures' texts (blank-line separated)
    with one placeholder per image Capture, in capture order. Captures are
    stored as anchors: their `text_content` is never persisted.
    """
    if not captures:
        return None

    elements = [
        cap.text_content if cap.kind == "text" else IMG_PLACEHOLDER
        for cap in captures
        if cap.kind == "image" or (cap.text_content and cap.text_content.strip())
    ]
    cur = conn.execute(
        "INSERT INTO extracts (doc_id, type, text_content) VALUES (?, ?, ?)",
        (doc_id, _derive_type(captures), _BLOB_SEP.join(elements)),
    )
    extract_id = cur.lastrowid

    for order, cap in enumerate(captures):
        conn.execute(
            """
            INSERT INTO captures
                (extract_id, page, rect, kind, text_content, image_blob, display_order)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                extract_id,
                cap.page,
                _rect_to_str(cap.rect),
                cap.kind,
                None,
                cap.image_blob,
                order,
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
        SELECT id, doc_id, type, text_content FROM extracts
        WHERE doc_id = ?
        ORDER BY id DESC
        """,
        (doc_id,),
    ).fetchall()

    extracts = []
    for eid, edoc, etype, blob in extract_rows:
        cap_rows = conn.execute(
            """
            SELECT id, page, rect, kind, text_content, image_blob, display_w
            FROM captures
            WHERE extract_id = ?
            ORDER BY COALESCE(display_order, id) ASC, id ASC
            """,
            (eid,),
        ).fetchall()
        captures = [
            Capture(
                id=cap_id,
                page=page,
                rect=_rect_from_str(rect),
                kind=kind,
                text_content=text_content,
                image_blob=image_blob,
                display_w=display_w,
            )
            for cap_id, page, rect, kind, text_content, image_blob, display_w in cap_rows
        ]
        extracts.append(
            Extract(id=eid, doc_id=edoc, type=etype, captures=captures, text_content=blob)
        )
    return extracts


_PREVIEW_LEN = 60


def preview_for_extract(extract: Extract) -> str:
    """One-line content preview for an Extract's row in the tree.

    First text chunk of the Extract's blob (whitespace-normalised,
    placeholders stripped, truncated to ~60 characters with an ellipsis).
    With no text: image placeholders present → the page span (`p. 4`,
    `pp. 4–5`, `pp. 1, 5`) of the images still displayed — a deleted
    placeholder shrinks a multi-page span (#44), pasted images (no PDF
    page, #48) are skipped and a pure-paste Extract previews `(pasted)`;
    none → `(empty)` — deleting an image from the document deletes it
    (Capture anchors stay). Derived at render time — never persisted.
    """
    blob = extract.text_content or ""
    for part in blob.split(_BLOB_SEP):
        snippet = " ".join(part.replace(IMG_PLACEHOLDER, " ").split())
        if snippet:
            if len(snippet) > _PREVIEW_LEN:
                return snippet[:_PREVIEW_LEN] + "…"
            return snippet

    if any(c.kind == "text" for c in extract.captures):
        return "(empty)"
    if IMG_PLACEHOLDER not in blob:
        # Images are deletable from the document: a pure image Extract
        # whose placeholders are all gone displays nothing.
        return "(empty)"

    images = [c for c in extract.captures if c.kind == "image" and c.image_blob]
    shown = images[: displayed_image_count(extract)]
    pages = sorted({c.page + 1 for c in shown if c.page is not None})
    if not pages:
        # Pasted images have no PDF page (#48): a pure-paste Extract
        # previews as such instead of masquerading as empty.
        return "(pasted)" if any(c.page is None for c in shown) else "(empty)"
    if len(pages) == 1:
        return f"p. {pages[0]}"
    if pages == list(range(pages[0], pages[-1] + 1)):
        return f"pp. {pages[0]}–{pages[-1]}"
    return "pp. " + ", ".join(str(p) for p in pages)


def displayed_image_count(extract: Extract) -> int:
    """How many of the Extract's image Captures the document displays.

    The blob's surviving placeholders map to image Captures in capture
    order — the same rule `_fill_editor_document` renders by — so the
    first `count` image Captures are in the document and the rest have
    been deleted from it; their anchor rows may be shown as such (#42).
    """
    images = [c for c in extract.captures if c.kind == "image" and c.image_blob]
    return min((extract.text_content or "").count(IMG_PLACEHOLDER), len(images))


def set_capture_display_w(conn, capture_id: int, width: Optional[int]) -> None:
    """Presentation-only display width for an image Capture (#37): NULL
    means the auto size band (#46). The page/rect geometry anchors and
    the blob are untouched — resize never re-renders the capture."""
    conn.execute(
        "UPDATE captures SET display_w = ? WHERE id = ?",
        (width, capture_id),
    )
    conn.commit()


def list_docs_with_extracts(conn) -> List[Tuple[int, Optional[str], Optional[str]]]:
    """(doc_id, name, path) for Documents that have at least one Extract.

    LEFT JOIN: Extracts are independent of the PDF (CONTEXT Q3/r5, #17),
    so a Document whose pdfs row was removed still appears — name and
    path come back None and the view marks it as a removed source.
    """
    rows = conn.execute(
        """
        SELECT DISTINCT e.doc_id, p.name, p.path
        FROM extracts e
        LEFT JOIN pdfs p ON p.id = e.doc_id
        ORDER BY e.doc_id
        """
    ).fetchall()
    return [(r[0], r[1], r[2]) for r in rows]


# (path -> (mtime, title)) so a refresh does not reopen every PDF.
_title_cache: dict = {}


def display_title(path: str, name: str) -> str:
    """Human-readable title for a Document row: the PDF's metadata title
    when present, else the filename cleaned up (`.pdf` stripped, `_` → space).

    Falls back to the cleaned filename for missing/unreadable files.
    Cached by (path, mtime) — a resaved PDF is re-read.
    """
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return _clean_fallback(name)

    cached = _title_cache.get(path)
    if cached is not None and cached[0] == mtime:
        return cached[1]

    title = _clean_fallback(name)
    try:
        import pymupdf

        with pymupdf.open(path) as doc:
            meta_title = ((doc.metadata or {}).get("title") or "").strip()
        if meta_title:
            title = meta_title
    except Exception:
        pass

    _title_cache[path] = (mtime, title)
    return title


def _clean_fallback(name: str) -> str:
    return Path(name).stem.replace("_", " ")


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


def _normalize_blob(text: str, image_count: int) -> str:
    """Reconcile the blob's placeholders with the Extract's image
    Captures: unbacked extras (pasted from the clipboard) are stripped
    from the end, while a deleted placeholder stays deleted — the
    Extract may display any subset of its image Captures, including
    none (the Capture rows remain as immutable page anchors)."""
    count = text.count(IMG_PLACEHOLDER)
    if image_count == 0:
        return text.replace(IMG_PLACEHOLDER, "")
    if count > image_count:
        for _ in range(count - image_count):
            idx = text.rfind(IMG_PLACEHOLDER)
            text = text[:idx] + text[idx + 1 :]
        text = text.rstrip()
    return text


def save_extract_text(
    conn,
    extract_id: int,
    text: str,
    image_backends: Optional[List] = None,
    pending_images: Optional[List] = None,
):
    """Persist an Extract's whole text blob (the joined editor document).

    Without `image_backends` the legacy rule applies: unbacked
    placeholders are stripped from the end (extras), a deleted
    placeholder stays deleted; returns True (False only when the
    Extract does not exist).

    With `image_backends` — one entry per placeholder in `text`, in
    document order, from the editor's QTextDocument walk (#48) —
    placeholder↔capture identity is exact instead of positional:
    an `int` is an existing capture id, `("paste", n)` creates a
    capture from `pending_images[n]` (page/rect NULL — pasted images
    have no PDF anchor), `None` strips the placeholder (not an image).
    Captures are then renumbered `display_order`: text captures first,
    the document's images in their exact order, then image anchors
    whose placeholder was deleted (kept, not rendered — blue redraw
    and Jump unaffected). Returns {paste_n: new_capture_id} on
    success, False when the Extract does not exist.
    """
    exists = conn.execute(
        "SELECT 1 FROM extracts WHERE id = ?", (extract_id,)
    ).fetchone()
    if exists is None:
        return False
    if image_backends is None:
        image_count = conn.execute(
            "SELECT COUNT(*) FROM captures WHERE extract_id = ? AND kind = 'image'",
            (extract_id,),
        ).fetchone()[0]
        conn.execute(
            "UPDATE extracts SET text_content = ? WHERE id = ?",
            (_normalize_blob(text, image_count), extract_id),
        )
        conn.commit()
        return True

    parts = text.split(IMG_PLACEHOLDER)
    if len(parts) - 1 != len(image_backends):
        # Defensive: both derive from the same document, so this should
        # not happen — fall back to the legacy count-based rule.
        image_count = conn.execute(
            "SELECT COUNT(*) FROM captures WHERE extract_id = ? AND kind = 'image'",
            (extract_id,),
        ).fetchone()[0]
        conn.execute(
            "UPDATE extracts SET text_content = ? WHERE id = ?",
            (_normalize_blob(text, image_count), extract_id),
        )
        conn.commit()
        return {}

    blob = ""
    kept: List = []
    for i, part in enumerate(parts):
        blob += part
        if i < len(parts) - 1:
            backend = image_backends[i]
            if backend is None:
                continue  # placeholder is not an image — strip it
            blob += IMG_PLACEHOLDER
            kept.append(backend)

    created: dict = {}
    image_seq: List[int] = []  # desired final order of rendered images
    for backend in kept:
        if isinstance(backend, tuple):
            n = backend[1]
            info = (pending_images or [])[n]
            cur = conn.execute(
                """
                INSERT INTO captures
                    (extract_id, page, rect, kind, text_content, image_blob, display_w)
                VALUES (?, NULL, NULL, 'image', NULL, ?, ?)
                """,
                (extract_id, info.get("blob"), info.get("display_w")),
            )
            created[n] = cur.lastrowid
            image_seq.append(cur.lastrowid)
        else:
            image_seq.append(backend)

    text_ids = [
        r[0]
        for r in conn.execute(
            """
            SELECT id FROM captures
            WHERE extract_id = ? AND kind = 'text'
            ORDER BY COALESCE(display_order, id) ASC, id ASC
            """,
            (extract_id,),
        ).fetchall()
    ]
    img_ids = [
        r[0]
        for r in conn.execute(
            """
            SELECT id FROM captures
            WHERE extract_id = ? AND kind = 'image'
            ORDER BY COALESCE(display_order, id) ASC, id ASC
            """,
            (extract_id,),
        ).fetchall()
    ]
    in_seq = set(image_seq)
    ordered = text_ids + image_seq + [i for i in img_ids if i not in in_seq]
    for rank, cid in enumerate(ordered):
        conn.execute(
            "UPDATE captures SET display_order = ? WHERE id = ?", (rank, cid)
        )
    conn.execute(
        "UPDATE extracts SET text_content = ? WHERE id = ?",
        (blob, extract_id),
    )
    conn.commit()
    return created


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