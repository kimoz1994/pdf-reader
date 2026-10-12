"""Export seams (#112): study data out of library.db as plain files.

Pure string builders — no Qt, no filesystem. The view owns the
QFileDialog and the write; these functions only format.
"""
import csv
import io
from typing import Iterable, List, Optional

from .extract_store import Extract, Flashcard

# Object-replacement char marks inline images in answer/extract blobs
# (#48) — exported as a readable token, not the raw U+FFFC.
IMG_TOKEN = "[image]"

# Anki's plain-text importer accepts a headerless or headed CSV; we
# write the header so the user can map columns, with the separator
# Anki expects for "Files in UTF-8" imports.
CSV_HEADER = ["Question", "Answer", "Source", "Due"]


def _text_with_images(text: Optional[str]) -> str:
    if not text:
        return ""
    return text.replace("\uFFFC", IMG_TOKEN)


def flashcards_to_csv(cards: Iterable[Flashcard]) -> str:
    """Anki-importable CSV: question, answer, source, due (#112).

    Proper csv-module quoting (a comma or newline in an answer never
    breaks a row); image placeholders become `[image]`; a missing
    source reads as `-` so the column never vanishes.
    """
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(CSV_HEADER)
    for card in cards:
        writer.writerow(
            [
                _text_with_images(card.question),
                _text_with_images(card.answer_text),
                card.source_name or "-",
                card.due_utc or "",
            ]
        )
    return buf.getvalue()


def extracts_to_markdown(
    docs: List[tuple],
    extracts_by_doc: dict,
) -> str:
    """One Markdown file: a `#` heading per Document, `##` per Extract,
    the text with `[image]` where inline images sit (#112).

    `docs` is `list_docs_with_extracts()` rows (doc_id, name, path);
    `extracts_by_doc` maps doc_id → `list_extracts_for_doc()` result.
    Newest-first extract order is kept as stored.
    """
    parts: List[str] = ["# Library exports", ""]
    for doc_id, name, _path in docs:
        title = name or f"Document {doc_id}"
        parts.append(f"# {title}")
        parts.append("")
        for extract in extracts_by_doc.get(doc_id, []):
            heading = f"Extract {extract.id}"
            parts.append(f"## {heading}")
            parts.append("")
            parts.append(_text_with_images(extract.text_content) or "*(empty)*")
            parts.append("")
    return "\n".join(parts).rstrip("\n") + "\n"
