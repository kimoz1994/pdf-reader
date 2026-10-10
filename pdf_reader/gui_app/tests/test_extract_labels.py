"""Source-name labels after removal (#70): the Extracts tree and the
Flashcards list keep showing the original PDF name instead of only an
internal id or `(source removed)`."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from services.extract_store import Flashcard
from views.extracts_view import _doc_label
from views.flashcards_view import _source_label


def test_removed_source_keeps_original_name():
    """The name snapshot replaces `⚠ Removed source (doc #N)` (#70)."""
    assert _doc_label(None, "book", 7) == "book ⚠ removed source"


def test_removed_source_without_snapshot_falls_back():
    """Pre-#70 Extracts have no snapshot — their names are gone, so the
    old marker stays."""
    assert _doc_label(None, None, 7) == "⚠ Removed source (doc #7)"


def test_live_doc_with_missing_file_still_marked():
    """#17 marker is unchanged: the row is there, the file is not."""
    missing = "C:/definitely/not/here/gone.pdf"
    assert _doc_label(missing, "gone.pdf", 7) == "gone ⚠ file missing"


def test_flashcard_source_label_keeps_snapshot_and_marker():
    """#70 for the Flashcards list: an orphaned card keeps the name and
    is marked the same way the tree marks a removed source."""
    card = Flashcard(id=1, question="Q?", answer_text="A.", source_name="book")
    assert _source_label(card) == "book ⚠ removed source"


def test_flashcard_source_label_without_snapshot_falls_back():
    card = Flashcard(id=1, question="Q?", answer_text="A.")
    assert _source_label(card) == "(source removed)"
