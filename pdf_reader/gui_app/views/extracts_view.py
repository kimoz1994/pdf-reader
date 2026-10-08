"""
Extracts View — browse captured material.

Shows the library's Documents, each expandable into its Extracts
(newest-first) — ONE row per Extract (#44). Activating a row swaps the tree
row swaps the tree for the full-area Extract Editor: ONE continuous
document — the whole Extract as a single editable surface where the
cursor flows across old capture boundaries and image Captures sit
inline (Save button and Back auto-save persist the Extract), with Back
returning to the exact tree row. Deleting an Extract removes it and its
Captures after confirmation. All data comes from the headless
persistence seam (`services.extract_store`).
"""
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QMessageBox,
    QAbstractItemView,
    QHeaderView,
    QScrollArea,
    QFrame,
    QTextEdit,
    QSizePolicy,
    QMenu,
    QDialog,
    QLineEdit,
)
from PyQt6.QtCore import Qt, QBuffer, QItemSelectionModel, QIODevice, QUrl, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QKeySequence,
    QShortcut,
    QImage,
    QAction,
    QTextCursor,
    QTextDocument,
    QTextImageFormat,
    QTextFormat,
    QTextOption,
)

from services.extract_store import (
    IMG_PLACEHOLDER,
    create_flashcard,
    delete_extract,
    display_title,
    list_docs_with_extracts,
    list_extracts_for_doc,
    preview_for_extract,
    save_extract_text,
    set_capture_display_w,
)
from services.selection_snapshot import snapshot_selection


def _doc_label(path, name, doc_id) -> str:
    """Doc-tree title, marked when the source is gone: the pdfs row was
    removed (path None) or the file is missing on disk (#17). Extracts
    themselves stay readable either way — content lives in the DB."""
    if path is None:
        return f"⚠ Removed source (doc #{doc_id})"
    title = display_title(path, name or "")
    if not Path(path).exists():
        return f"{title} ⚠ file missing"
    return title


def _extract_label(extract) -> str:
    """Tree row label: identity + live content preview."""
    count = len(extract.captures)
    base = (
        f"Extract #{extract.id} — {extract.type} "
        f"({count} capture{'s' if count != 1 else ''})"
    )
    return f"{base}: {preview_for_extract(extract)}"


# Display band for inline images in the Extract Editor (#46): sources
# narrower than the floor upscale to it (pre-#36 captures are 1x DPI and
# read tiny otherwise), wider than the cap downscale. Aspect kept.
_IMG_MIN_W = 480
_IMG_MAX_W = 860
# Explicit resize bounds and step for the editor's image sizing (#37):
# Bigger/Smaller move by _RESIZE_STEP px; values outside [MIN, MAX] clamp.
_IMG_W_MIN = 100
_IMG_W_MAX = 4000
_RESIZE_STEP = 60

# Readable context menu over the light editor paper: the menu inherits
# the paper background from `editor_doc`'s stylesheet while its text
# follows the OS palette — white text on white in Windows dark mode.
# Explicit colors make it independent of both.
_CONTEXT_MENU_CSS = """
QMenu {
    background-color: #2b2b2b;
    color: #ecf0f1;
    border: 1px solid #3d566e;
    padding: 4px;
}
QMenu::item {
    padding: 5px 26px 5px 22px;
    background-color: transparent;
}
QMenu::item:selected {
    background-color: #3498db;
    color: white;
}
QMenu::item:disabled {
    color: #7f8c8d;
}
QMenu::separator {
    height: 1px;
    background-color: #3d566e;
    margin: 4px 10px;
}
"""


class _ExtractDocEdit(QTextEdit):
    """The whole Extract as ONE editable document inside the Extract
    Editor.

    All of the Extract's text lives in a single surface — the cursor
    flows across the old capture boundaries and there is one undo
    history — while image Captures render inline (Qt's object
    replacement character), so text can be typed before, after and
    between images. Wraps at the block width — soft line breaks never
    change the Captures — and grows its height to fit the content.
    Height feeds the viewport width into the document explicitly
    (`setTextWidth`) because only then does `document().size()` return
    real pixels; always recalculating for the live width keeps long
    documents fully visible instead of clipped.
    """

    # (document resource URL, new width in px; None = auto band).
    resize_requested = pyqtSignal(str, object)
    # A clipboard QImage was pasted (#48) — the view inserts + tracks it.
    pasted_image = pyqtSignal(object)
    # The reader asked for a flashcard from the current selection (#55).
    make_flashcard_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setObjectName("extract_doc")
        self.setAcceptRichText(False)
        self.document().setDocumentMargin(4)
        self.setWordWrapMode(QTextOption.WrapMode.WordWrap)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(
            """
            QTextEdit {
                background: transparent;
                border: none;
                color: #1a1a1a;
                font-size: 17px;
            }
            """
        )
        self.textChanged.connect(self._sync_height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_height()

    def _sync_height(self):
        """Size the now-unconstrained document to the viewport width and
        match the widget height to the full-space document height —
        that height already contains its own 2x document margin, so no
        extra slack is added here."""
        width = self.viewport().width()
        if width <= 0:
            return
        doc = self.document()
        doc.setTextWidth(width)
        height = int(doc.size().height()) + self.frameWidth() * 2
        if self.height() != height:
            self.setFixedHeight(height)

    def _image_url_at_cursor(self, cursor, prefer_start=False):
        """Document resource URL of the image at the cursor, immediately
        before it, or starting at it, else None. capimg:// = a saved
        capture, paste:// = a session-pending pasted image (#37/#48).

        Qt reports an image's charFormat() at its own index or at +1
        depending on the preceding character, and adjacent images shadow
        each other — so each candidate index is resolved with an
        adjacency-aware probe (skip the shadowed index, fall back to the
        +1 extension). Keys prefer the image ENDING at the cursor (the
        post-paste state sits right after the new image); the context
        menu passes prefer_start when the click landed on the right side
        of the caret, picking the image that STARTS at the cursor."""
        doc = self.document()
        count = doc.characterCount()

        def probe(p):
            if 0 <= p < count:
                pc = QTextCursor(doc)
                pc.setPosition(p)
                fmt = pc.charFormat()
                if fmt.isImageFormat():
                    name = fmt.property(QTextFormat.Property.ImageName)
                    if isinstance(name, str) and (
                        name.startswith("capimg://") or name.startswith("paste://")
                    ):
                        return name
            return None

        def resolve(q):
            left_adj = q >= 1 and doc.characterAt(q - 1) == IMG_PLACEHOLDER
            for p in ((q + 1, q) if left_adj else (q, q + 1)):
                name = probe(p)
                if name is not None:
                    return name
            return None

        pos = cursor.position()
        before = pos >= 1 and doc.characterAt(pos - 1) == IMG_PLACEHOLDER
        at = 0 <= pos < count and doc.characterAt(pos) == IMG_PLACEHOLDER
        if prefer_start and at:
            return resolve(pos)
        if before:
            return resolve(pos - 1)
        if at:
            return resolve(pos)
        return None

    def _rendered_width(self, url):
        """Currently displayed width (px) of the image under `url`,
        from its document resource — band-clamped or user-sized."""
        img = self.document().resource(
            QTextDocument.ResourceType.ImageResource, QUrl(url)
        )
        if isinstance(img, QImage) and not img.isNull():
            return img.width()
        return None

    def _emit_resize(self, url, delta):
        cur = self._rendered_width(url)
        if cur is None:
            return
        self.resize_requested.emit(
            url, min(max(cur + delta, _IMG_W_MIN), _IMG_W_MAX)
        )

    def _image_resize_actions(self, url):
        """Bigger/Smaller/Reset actions for one image (#37): presentation
        only — the view persists display_w and re-renders in place."""
        bigger = QAction("Bigger  (+)", self)
        bigger.triggered.connect(lambda: self._emit_resize(url, _RESIZE_STEP))
        smaller = QAction("Smaller  (-)", self)
        smaller.triggered.connect(lambda: self._emit_resize(url, -_RESIZE_STEP))
        reset = QAction("Reset to auto size", self)
        reset.triggered.connect(lambda: self.resize_requested.emit(url, None))
        return [bigger, smaller, reset]

    def has_selection(self) -> bool:
        return bool(self.textCursor().hasSelection())

    def request_flashcard(self):
        """The ONE gated action path shared by the entry points
        (right-click #55, Ctrl+K #57): emit only when selected."""
        if self.has_selection():
            self.make_flashcard_requested.emit()

    def contextMenuEvent(self, event):
        cursor = self.cursorForPosition(event.pos())
        # Click right of the caret -> the image starting there; left of
        # it -> the image ending there (adjacent pairs resolve cleanly).
        caret = self.cursorRect(cursor)
        prefer_start = event.pos().x() >= caret.left()
        url = self._image_url_at_cursor(cursor, prefer_start=prefer_start)
        # Built by hand (not super()) so both branches can offer the
        # flashcard action when a selection exists (#55).
        menu = self.createStandardContextMenu(event.globalPos())
        menu.setStyleSheet(_CONTEXT_MENU_CSS)
        if self.has_selection():
            menu.addSeparator()
            make_card = QAction("🃏 Make flashcard…", self)
            make_card.triggered.connect(self.request_flashcard)
            menu.addAction(make_card)
        if url is not None:
            menu.addSeparator()
            menu.addActions(self._image_resize_actions(url))
        menu.exec(event.globalPos())

    def insertFromMimeData(self, source):
        """Paste: a clipboard image becomes an inline pasted image (#48)
        — emitted for the view to store and render; anything else falls
        through to the default (plain-text) paste."""
        if source.hasImage():
            image = source.imageData()
            if isinstance(image, QImage) and not image.isNull():
                self.pasted_image.emit(image)
                return
        super().insertFromMimeData(source)

    def keyPressEvent(self, event):
        """Ctrl+K = Make flashcard (#57): same dialog as the right-click
        entry when a selection exists, inert otherwise — consumed so it
        can never fall through to the native delete-to-end-of-line
        binding. +/- resize the adjacent image instead of typing — only
        when the cursor sits on/next to an image and nothing is selected;
        text edits keep their literal +/- as before (#37)."""
        if (
            event.key() == Qt.Key.Key_K
            and event.modifiers() == Qt.KeyboardModifier.ControlModifier
        ):
            self.request_flashcard()
            return
        key = event.key()
        bigger = key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal)
        smaller = key in (Qt.Key.Key_Minus, Qt.Key.Key_Underscore)
        if bigger or smaller:
            cursor = self.textCursor()
            if not cursor.hasSelection():
                # any modifiers (Ctrl+± is a common habit) — the image
                # wins only when the cursor actually sits on one
                url = self._image_url_at_cursor(cursor)
                if url is not None:
                    self._emit_resize(
                        url, _RESIZE_STEP if bigger else -_RESIZE_STEP
                    )
                    return
        super().keyPressEvent(event)


class _FlashcardDialog(QDialog):
    """Modal Make-flashcard dialog (#55): the selection as the answer,
    a question field, Add / Cancel. Escape rejects (QDialog default);
    Add stays disabled while the question is empty."""

    def __init__(self, answer_text, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Make Flashcard")
        self.setModal(True)
        self.resize(560, 480)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        layout.addWidget(QLabel("Answer (from your selection):"))
        self.answer_view = QTextEdit()
        self.answer_view.setReadOnly(True)
        self.answer_view.setPlainText(answer_text)
        self.answer_view.setStyleSheet(
            # Explicit color: without it the OS dark-mode palette paints
            # white text on this light paper → invisible (#55 follow-up,
            # same root cause as the context menu).
            "background-color: #f7f7f5; color: #1a1a1a;"
            " border: 1px solid #d0d0d0;"
            " border-radius: 6px; padding: 8px; font-size: 14px;"
        )
        layout.addWidget(self.answer_view, 1)

        layout.addWidget(QLabel("Question:"))
        self.question_edit = QLineEdit()
        self.question_edit.setPlaceholderText(
            "Ask a question about this answer…"
        )
        layout.addWidget(self.question_edit)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(cancel_btn)
        self.add_btn = QPushButton("Add Flashcard")
        self.add_btn.setEnabled(False)
        self.add_btn.clicked.connect(self.accept)
        self.question_edit.textChanged.connect(
            lambda text: self.add_btn.setEnabled(bool(text.strip()))
        )
        # Keyboard flow (#57): Enter in the question field adds the card
        # as soon as it has one; empty → no-op (Add stays the gate).
        self.question_edit.returnPressed.connect(self._submit_if_ready)
        buttons.addWidget(self.add_btn)
        layout.addLayout(buttons)

    def question(self) -> str:
        return self.question_edit.text()

    def _submit_if_ready(self):
        if self.add_btn.isEnabled():
            self.accept()

    def showEvent(self, event):
        # The question field is autofocused on open (#55).
        super().showEvent(event)
        self.question_edit.setFocus()


class ExtractsView(QWidget):
    # Payload: {"path", "page", "rect", "extract_id"} for the first Capture
    jump_requested = pyqtSignal(dict)
    def __init__(self):
        super().__init__()
        self.setup_ui()

    def _db_conn(self):
        """The shared sqlite connection MainWindow keeps open, or None."""
        main_window = self.window()
        if hasattr(main_window, "db_conn"):
            return main_window.db_conn()
        return None

    def setup_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(15)

        header = QLabel("📝 Extracts")
        header.setStyleSheet("font-size: 28px; font-weight: bold; color: #3498db;")
        self.header_label = header
        layout.addWidget(header)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        self.refresh_btn = QPushButton("🔄 Refresh")
        self.refresh_btn.setFixedHeight(40)
        self.refresh_btn.clicked.connect(self.refresh)
        buttons.addWidget(self.refresh_btn)

        self.delete_btn = QPushButton("🗑️ Delete Selected")
        self.delete_btn.setFixedHeight(40)
        self.delete_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #e74c3c;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 15px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #c0392b;
            }
            """
        )
        self.delete_btn.clicked.connect(self.delete_selected)
        buttons.addWidget(self.delete_btn)
        buttons.addStretch()
        layout.addLayout(buttons)

        self.empty_label = QLabel("No extracts yet.\n\nCapture text or images in the reader, then commit with e.")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet("color: #888; font-size: 16px;")
        self.empty_label.hide()
        layout.addWidget(self.empty_label)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Extracts", ""])
        self.tree.setColumnWidth(1, 90)
        # Column 0 (labels + previews) takes all spare width; the Jump
        # column stays at 90px. Without this the default stretch-last-section
        # squeezes col 0 to ~100px and elides every preview away.
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.setStyleSheet(
            """
            QTreeWidget {
                background-color: #2b2b2b;
                color: #ecf0f1;
                border: none;
                border-radius: 8px;
                padding: 10px;
                font-size: 14px;
            }
            QTreeWidget::item {
                padding: 4px;
            }
            """
        )
        layout.addWidget(self.tree)

        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.itemActivated.connect(self._on_item_activated)

        # No Qt edit triggers: single-click must only select, and
        # Enter/double-click is owned by _on_item_activated (which opens
        # the Extract Editor — the only place where text is edited).
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        self._build_editor_page(layout)
        self._return_item = None
        self._return_expanded = []
        self._editor_open = False
        self._editor_dirty = False
        self._editor_extract_id = None
        self._editor_doc_id = None
        self._editor_doc_edit = None
        self._editor_images = []  # image Captures rendered in the editor (#37)
        self._editor_pastes = []  # pending pasted images, not yet captures (#48)
        self._suppress_dirty = False  # format-only changes keep Save off

        self.setLayout(layout)
        self.refresh()

    def _build_editor_page(self, layout):
        """The full-area Extract Editor: Back + Save + title + a scrollable
        paper document — ONE continuous editable surface for the Extract."""
        self.editor_page = QWidget()
        ed = QVBoxLayout(self.editor_page)
        ed.setContentsMargins(30, 30, 30, 30)
        ed.setSpacing(15)

        back_row = QHBoxLayout()
        self.back_btn = QPushButton("← Back")
        self.back_btn.setFixedHeight(40)
        self.back_btn.setStyleSheet(
            """
            QPushButton {
                background-color: transparent;
                color: #3498db;
                border: 1px solid #3498db;
                border-radius: 8px;
                font-size: 15px;
                font-weight: bold;
                padding: 0 18px;
            }
            QPushButton:hover { background-color: #3498db; color: white; }
            """
        )
        self.back_btn.clicked.connect(self._close_editor)
        back_row.addWidget(self.back_btn)

        # Save persists mid-session edits without leaving the editor;
        # disabled until something changes (Back auto-saves regardless).
        self.save_btn = QPushButton("💾 Save")
        self.save_btn.setFixedHeight(40)
        self.save_btn.setEnabled(False)
        self.save_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #3498db;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 15px;
                font-weight: bold;
                padding: 0 18px;
            }
            QPushButton:hover { background-color: #2980b9; }
            QPushButton:disabled { background-color: #bdc3c7; color: #f0f0f0; }
            """
        )
        self.save_btn.clicked.connect(self._save_editor)
        back_row.addWidget(self.save_btn)

        # Toolbar flashcard entry (#57): same dialog as right-click and
        # Ctrl+K — enabled only while the editor has a selection.
        self.flashcard_btn = QPushButton("🃏 Make flashcard")
        self.flashcard_btn.setFixedHeight(40)
        self.flashcard_btn.setEnabled(False)
        self.flashcard_btn.setStyleSheet(
            """
            QPushButton {
                background-color: transparent;
                color: #3498db;
                border: 1px solid #3498db;
                border-radius: 8px;
                font-size: 15px;
                font-weight: bold;
                padding: 0 18px;
            }
            QPushButton:hover { background-color: #3498db; color: white; }
            QPushButton:disabled { color: #bdc3c7; border-color: #bdc3c7; }
            """
        )
        self.flashcard_btn.clicked.connect(self._make_flashcard)
        back_row.addWidget(self.flashcard_btn)
        back_row.addStretch()
        ed.addLayout(back_row)

        self.editor_title = QLabel()
        self.editor_title.setStyleSheet(
            "font-size: 22px; font-weight: bold; color: #3498db;"
        )
        ed.addWidget(self.editor_title)

        # Ctrl+K entry (#57) with a page-wide context: fires with focus
        # anywhere on the editor page (editor, Save, Back) and routes to
        # the same gated handler as the toolbar button; the editor's
        # keyPressEvent covers the case where QTextEdit claims the key
        # first — the two can never both fire, and both end at
        # _make_flashcard.
        self.ctrl_k_shortcut = QShortcut(
            QKeySequence("Ctrl+K"), self.editor_page
        )
        self.ctrl_k_shortcut.setContext(
            Qt.ShortcutContext.WidgetWithChildrenShortcut
        )
        self.ctrl_k_shortcut.activated.connect(self._make_flashcard)

        self.editor_scroll = QScrollArea()
        self.editor_scroll.setWidgetResizable(True)
        self.editor_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.editor_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
        )
        self.editor_doc = QWidget()
        self.editor_doc.setStyleSheet(
            "background-color: #f7f7f5; border-radius: 8px;"
        )
        self.editor_layout = QVBoxLayout(self.editor_doc)
        self.editor_layout.setContentsMargins(40, 30, 40, 30)
        self.editor_layout.setSpacing(18)
        self.editor_layout.addStretch()
        self.editor_scroll.setWidget(self.editor_doc)
        ed.addWidget(self.editor_scroll)

        self.editor_page.hide()
        layout.addWidget(self.editor_page)

    def refresh(self):
        """Reload the Document -> Extract hierarchy (one row per Extract)."""
        if self._editor_open:
            # Re-entering via the sidebar refreshes the view while the
            # editor is open; close first so Back never targets tree
            # items that clear() is about to destroy. State-based, not
            # isVisible(): the page can be hidden under the stack while
            # the editor is open (e.g. after a Jump to the reader).
            self._close_editor()
        # Belt: these item refs die with the clear below no matter what.
        self._return_item = None
        self._return_expanded = []
        self.tree.clear()
        conn = self._db_conn()
        if conn is None:
            return
        doc_ids = list_docs_with_extracts(conn)
        rows = []
        for doc_id, name, path in doc_ids:
            extracts = list_extracts_for_doc(conn, doc_id)
            rows.append((name, path, doc_id, extracts))

        if not rows:
            self.empty_label.show()
            self.tree.hide()
            return
        self.empty_label.hide()
        self.tree.show()

        for name, path, doc_id, extracts in rows:
            doc_item = QTreeWidgetItem([_doc_label(path, name, doc_id)])
            doc_item.setData(0, Qt.ItemDataRole.UserRole, {"doc_id": doc_id})
            for extract in extracts:
                # Pasted images have no page (#48): jump anchors on the
                # first capture that has one; pure-paste rows hide ↱.
                first_cap = next(
                    (c for c in extract.captures if c.page is not None), None
                )
                ex_item = QTreeWidgetItem(
                    [_extract_label(extract), "↱ Jump" if first_cap else ""]
                )
                ex_item.setData(
                    0, Qt.ItemDataRole.UserRole,
                    {
                        "doc_id": doc_id,
                        "extract_id": extract.id,
                        "path": path,
                        "page": first_cap.page if first_cap else None,
                        "rect": first_cap.rect if first_cap else None,
                    },
                )
                ex_item.setForeground(1, QBrush(QColor("#3498db")))
                # One row per Extract (#44): the label's capture count and
                # preview already carry the composition — per-image anchor
                # rows read as duplicated content. Captures stay fully
                # visible in the editor and as blue anchors in the reader.
                doc_item.addChild(ex_item)
            doc_item.setExpanded(True)
            self.tree.addTopLevelItem(doc_item)

        self.tree.expandAll()

    def _on_item_clicked(self, item, column):
        """Click on the Jump column of an Extract row triggers a jump."""
        if column != 1:
            return
        self._jump_from_item(item)

    def _on_item_activated(self, item, column):
        """Enter/double-click: the ↱ column still jumps; any other row
        opens the full-area Extract Editor."""
        if column == 1:
            self._jump_from_item(item)
            return
        self._open_editor(item)

    def _open_editor(self, item):
        """Open the editor for the Extract owning `item`. Document rows
        are a no-op (they own no single Extract). The parent fallback
        for capture rows is dormant since the tree shows one row per
        Extract (#44) — kept as defense."""
        data = item.data(0, Qt.ItemDataRole.UserRole) or {}
        if data.get("extract_id") is None:
            parent = item.parent()
            data = (parent.data(0, Qt.ItemDataRole.UserRole) or {}) if parent else {}
        if data.get("extract_id") is None or data.get("doc_id") is None:
            return
        conn = self._db_conn()
        if conn is None:
            return
        extract = next(
            (
                e
                for e in list_extracts_for_doc(conn, data["doc_id"])
                if e.id == data["extract_id"]
            ),
            None,
        )
        if extract is None:
            return
        self._show_editor(extract, data, item)

    def _show_editor(self, extract, data, origin_item):
        """Swap the tree page for the editor and render the document."""
        # Remember tree state so Back can return to exactly this row.
        self._return_item = origin_item
        self._return_expanded = []
        for i in range(self.tree.topLevelItemCount()):
            doc_item = self.tree.topLevelItem(i)
            self._return_expanded.append((doc_item, doc_item.isExpanded()))
            for j in range(doc_item.childCount()):
                ex_item = doc_item.child(j)
                self._return_expanded.append((ex_item, ex_item.isExpanded()))

        path = data.get("path") or ""
        title = f"Extract #{extract.id} — {extract.type}"
        if path:
            title += f"  ·  {display_title(path, Path(path).name)}"
        self.editor_title.setText(title)

        self._editor_extract_id = extract.id
        self._editor_doc_id = data.get("doc_id")
        self._editor_dirty = False
        self.save_btn.setEnabled(False)
        self.flashcard_btn.setEnabled(False)
        self._editor_doc_edit = None

        while self.editor_layout.count():
            block = self.editor_layout.takeAt(0)
            w = block.widget()
            if w is not None:
                w.deleteLater()
        edit = _ExtractDocEdit()
        self._fill_editor_document(edit, extract)
        # Connected after the fill: building the document is not an edit.
        edit.textChanged.connect(self._mark_dirty)
        edit.resize_requested.connect(self._on_image_resize)
        edit.pasted_image.connect(self._on_pasted_image)
        edit.make_flashcard_requested.connect(self._make_flashcard)
        edit.selectionChanged.connect(self._sync_flashcard_btn)
        self.editor_layout.addWidget(edit)
        self._editor_doc_edit = edit
        self.editor_layout.addStretch()

        self.header_label.hide()
        self.refresh_btn.hide()
        self.delete_btn.hide()
        self.empty_label.hide()
        self.tree.hide()
        self.editor_page.show()
        self._editor_open = True
        self.editor_scroll.verticalScrollBar().setValue(0)
        self.back_btn.setFocus()

    def _fill_editor_document(self, edit, extract):
        """Build the one joined document: the blob's text with each image
        Capture rendered inline at its placeholder position, in capture
        order. Only real placeholders render an image — deleted ones stay
        deleted (surviving placeholders map to captures in capture
        order), so an emptied blob builds an empty document."""
        blob = extract.text_content or ""
        images = [c for c in extract.captures if c.kind == "image" and c.image_blob]
        self._editor_images = images  # index -> capimg://<i> (#37)
        parts = blob.split(IMG_PLACEHOLDER)
        cursor = edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        for i, part in enumerate(parts):
            if part:
                cursor.insertText(part)
            if i < len(parts) - 1 and i < len(images):
                cursor.insertImage(
                    self._image_format(
                        edit.document(),
                        images[i].image_blob,
                        images[i].display_w,
                        f"capimg://{i}",
                    )
                )

    def _image_format(self, doc, blob, display_w, url):
        """Inline image format for one image source: decoded PNG
        registered as a document resource under `url`, displayed at an
        explicit `display_w` when set (#37), else within the size band
        (_IMG_MIN_W.._IMG_MAX_W, aspect kept): small sources upscale to
        the floor so they read at a comfortable size next to the note
        text (#46), oversized sources downscale to the cap."""
        image = QImage.fromData(blob)
        if not image.isNull():
            if display_w:
                target = min(max(int(display_w), _IMG_W_MIN), _IMG_W_MAX)
            else:
                target = min(max(image.width(), _IMG_MIN_W), _IMG_MAX_W)
            if target != image.width():
                image = image.scaledToWidth(
                    target, Qt.TransformationMode.SmoothTransformation
                )
        doc.addResource(QTextDocument.ResourceType.ImageResource, QUrl(url), image)
        fmt = QTextImageFormat()
        fmt.setName(url)
        if not image.isNull():
            fmt.setWidth(float(image.width()))
            fmt.setHeight(float(image.height()))
        return fmt

    def _on_pasted_image(self, qimg):
        """A clipboard image was pasted (#48): keep its PNG blob as a
        pending capture and render it inline at once (auto band until
        resized). The capture row is created on the next Save."""
        if self._editor_doc_edit is None:
            return
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        qimg.save(buf, "PNG")
        blob = bytes(buf.data())
        n = len(self._editor_pastes)
        self._editor_pastes.append(
            {"blob": blob, "display_w": None, "capture_id": None}
        )
        url = f"paste://{n}"
        fmt = self._image_format(self._editor_doc_edit.document(), blob, None, url)
        self._editor_doc_edit.textCursor().insertImage(fmt)

    def _on_image_resize(self, url, width):
        """(Re)size an inline image from the context menu or +/- keys
        (#37/#48): capimg://n persists display_w on the capture row;
        paste://n updates the session-pending image (and its row too
        once Save has created it). Text is byte-identical, Save stays
        off for saved images."""
        if not self._editor_open or self._editor_doc_edit is None:
            return
        if url.startswith("capimg://"):
            try:
                index = int(url[len("capimg://"):])
            except ValueError:
                return
            if not (0 <= index < len(self._editor_images)):
                return
            cap = self._editor_images[index]
            if width is not None:
                width = min(max(int(width), _IMG_W_MIN), _IMG_W_MAX)
                if width == cap.display_w:
                    return
            elif cap.display_w is None:
                return
            conn = self._db_conn()
            if conn is None:
                return
            set_capture_display_w(conn, cap.id, width)
            cap.display_w = width
            blob, display_w = cap.image_blob, cap.display_w
        elif url.startswith("paste://"):
            try:
                n = int(url[len("paste://"):])
            except ValueError:
                return
            if not (0 <= n < len(self._editor_pastes)):
                return
            entry = self._editor_pastes[n]
            if width is not None:
                width = min(max(int(width), _IMG_W_MIN), _IMG_W_MAX)
                if width == entry["display_w"]:
                    return
            elif entry["display_w"] is None:
                return
            entry["display_w"] = width
            if entry["capture_id"] is not None:
                conn = self._db_conn()
                if conn is not None:
                    set_capture_display_w(conn, entry["capture_id"], width)
            blob, display_w = entry["blob"], entry["display_w"]
        else:
            return
        self._suppress_dirty = True
        try:
            self._re_render_image(url, blob, display_w)
        finally:
            self._suppress_dirty = False

    def _re_render_image(self, url, blob, display_w):
        """Swap the image under `url` in place: register the newly
        sized pixmap and rewrite the format on the single document
        position holding it. Cursor and text untouched."""
        doc = self._editor_doc_edit.document()
        fmt = self._image_format(doc, blob, display_w, url)
        cursor = QTextCursor(doc)
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        while True:
            cur_fmt = cursor.charFormat()
            if cur_fmt.isImageFormat() and cur_fmt.property(
                QTextFormat.Property.ImageName
            ) == url:
                # Qt quirk (see _image_backends): the match position m may
                # be the image's own index, its +1 extension point, or the
                # previous image's shadow on an adjacent placeholder.
                # Resolve the real image index and swap that one char.
                m = cursor.position()
                at_m = doc.characterAt(m) == IMG_PLACEHOLDER
                prev_is_img = m >= 1 and doc.characterAt(m - 1) == IMG_PLACEHOLDER
                if at_m and not prev_is_img:
                    k = m
                elif prev_is_img:
                    k = m - 1
                else:
                    return  # unlocatable: format nothing rather than a neighbor
                cursor.setPosition(k)
                cursor.setPosition(k + 1, QTextCursor.MoveMode.KeepAnchor)
                cursor.setCharFormat(fmt)
                return
            if not cursor.movePosition(QTextCursor.MoveOperation.NextCharacter):
                return

    def _image_backends(self):
        """Per-placeholder backend in document order, from the live
        QTextDocument (#48): int = existing capture id, ("paste", n) =
        session-pending paste, None = a U+FFFC that carries no image
        (stripped on save). Exact identity — no positional guessing.

        Qt quirk: QTextCursor.charFormat() at position p reports an
        image at p or p-1 depending on the preceding character, and
        adjacent images shadow each other. So each placeholder p is
        probed at p then p+1, skipping the previously resolved image's
        name (an adjacent image's format leaking in)."""
        doc = self._editor_doc_edit.document()
        backends = []
        prev_name = None
        for pos in range(doc.characterCount()):
            if doc.characterAt(pos) != IMG_PLACEHOLDER:
                continue
            name = None
            for probe_pos in (pos, pos + 1):
                if probe_pos >= doc.characterCount():
                    break
                probe = QTextCursor(doc)
                probe.setPosition(probe_pos)
                fmt = probe.charFormat()
                if not fmt.isImageFormat():
                    continue
                cand = fmt.property(QTextFormat.Property.ImageName)
                if isinstance(cand, str) and cand != prev_name:
                    name = cand
                    break
            prev_name = name
            backend = None
            if isinstance(name, str) and name.startswith("capimg://"):
                try:
                    i = int(name[len("capimg://"):])
                except ValueError:
                    i = -1
                if 0 <= i < len(self._editor_images):
                    backend = self._editor_images[i].id
            elif isinstance(name, str) and name.startswith("paste://"):
                try:
                    n = int(name[len("paste://"):])
                except ValueError:
                    n = -1
                if 0 <= n < len(self._editor_pastes):
                    saved_id = self._editor_pastes[n]["capture_id"]
                    backend = saved_id if saved_id is not None else ("paste", n)
            backends.append(backend)
        return backends

    def _mark_dirty(self):
        """The document changed: enable Save (Back would auto-save anyway).

        Suppressed while an image resize re-renders (#37): the text blob
        is byte-identical, so there is nothing for Save to persist."""
        if self._suppress_dirty:
            return
        self._editor_dirty = True
        self.save_btn.setEnabled(True)

    def _sync_flashcard_btn(self):
        """Toolbar entry (#57): the flashcard button tracks the editor's
        selection — enabled only while there is one."""
        edit = self._editor_doc_edit
        self.flashcard_btn.setEnabled(
            edit is not None and edit.has_selection()
        )

    def _make_flashcard(self):
        """Right-click → 🃏 Make flashcard… (#55): snapshot the live
        selection (editor buffer — saved or unsaved state alike), let the
        reader type a question, and persist one card. The answer is a
        copy: later Extract edits never touch it."""
        if not self._editor_open or self._editor_doc_edit is None:
            return
        cursor = self._editor_doc_edit.textCursor()
        if not cursor.hasSelection():
            return
        # Image blobs come back with the text snapshot but are persisted
        # only with image flashcards (#56) — text cards store the
        # placeholder alone for now.
        answer_text, _image_blobs = snapshot_selection(
            self._editor_doc_edit.document(), cursor
        )
        if not answer_text.strip():
            window = self.window()
            if hasattr(window, "statusBar"):
                window.statusBar().showMessage("Nothing to flash here", 5000)
            return
        conn = self._db_conn()
        if conn is None:
            return
        dialog = _FlashcardDialog(answer_text, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        question = dialog.question().strip()
        if not question:
            return
        create_flashcard(
            conn,
            question=question,
            answer_text=answer_text,
            extract_id=self._editor_extract_id,
            doc_id=self._editor_doc_id,
        )
        window = self.window()
        if hasattr(window, "statusBar"):
            window.statusBar().showMessage("Flashcard added", 5000)

    def _save_editor(self):
        """Persist the whole joined document (shared by the Save button
        and Back auto-save) and refresh the origin Extract's row label in
        place, so Back's selection/expansion restore hits live items."""
        if (
            not self._editor_open
            or self._editor_extract_id is None
            or self._editor_doc_edit is None
        ):
            return False
        conn = self._db_conn()
        if conn is None:
            return False
        result = save_extract_text(
            conn,
            self._editor_extract_id,
            self._editor_doc_edit.toPlainText(),
            image_backends=self._image_backends(),
            pending_images=self._editor_pastes,
        )
        if result is False:
            return False
        if isinstance(result, dict):
            for n, capture_id in result.items():
                self._editor_pastes[n]["capture_id"] = capture_id
        self._editor_dirty = False
        self.save_btn.setEnabled(False)
        self._sync_tree_preview()
        return True

    def _sync_tree_preview(self):
        """Update the origin Extract's row label from the DB without
        rebuilding the tree (structure never changes: count, pages and
        rects are untouched by edits)."""
        conn = self._db_conn()
        if conn is None or self._editor_extract_id is None or self._return_item is None:
            return
        origin_data = self._return_item.data(0, Qt.ItemDataRole.UserRole) or {}
        ex_item = (
            self._return_item
            if origin_data.get("extract_id") == self._editor_extract_id
            else self._return_item.parent()
        )
        if ex_item is None:
            return
        extract = next(
            (
                e
                for e in list_extracts_for_doc(conn, self._editor_doc_id)
                if e.id == self._editor_extract_id
            ),
            None,
        )
        if extract is None:
            return
        ex_item.setText(0, _extract_label(extract))

    def _close_editor(self):
        """Back: auto-save pending edits, hide the editor, restore the tree
        exactly as it was."""
        if self._editor_dirty:
            self._save_editor()
        self.editor_page.hide()
        self.header_label.show()
        self.refresh_btn.show()
        self.delete_btn.show()
        if self.tree.topLevelItemCount():
            self.tree.show()
        else:
            self.empty_label.show()
        for item, expanded in self._return_expanded:
            item.setExpanded(expanded)
        if self._return_item is not None:
            self.tree.setCurrentItem(
                self._return_item,
                0,
                QItemSelectionModel.SelectionFlag.ClearAndSelect,
            )
            self.tree.scrollToItem(self._return_item)
        self._return_item = None
        self._return_expanded = []
        self._editor_open = False
        self._editor_dirty = False
        self._editor_extract_id = None
        self._editor_doc_id = None
        self._editor_doc_edit = None
        self._editor_images = []  # image Captures rendered in the editor (#37)
        self._editor_pastes = []  # pending pasted images, not yet captures (#48)
        self._suppress_dirty = False  # format-only changes keep Save off
        self.save_btn.setEnabled(False)
        self.tree.setFocus()

    def _jump_from_item(self, item):
        data = item.data(0, Qt.ItemDataRole.UserRole) or {}
        if data.get("page") is None:
            # path may be None for a removed source — MainWindow's
            # on_extract_jump raises the "PDF Removed" warning (#17).
            return
        self.jump_requested.emit(dict(data))

    def _extract_id_for_item(self, item):
        """The Extract id owning `item` — the Extract row itself or one
        of its image Capture rows; None for Document rows / no
        selection. Same resolution `_open_editor` uses."""
        if item is None:
            return None
        data = item.data(0, Qt.ItemDataRole.UserRole) or {}
        if data.get("extract_id") is None:
            parent = item.parent()
            data = (parent.data(0, Qt.ItemDataRole.UserRole) or {}) if parent else {}
        return data.get("extract_id")

    def delete_selected(self):
        """Delete the selected Extract after a confirmation popup.

        An image Capture row selects its owning Extract (Captures are
        anchors — they go only with it). Document rows and empty
        selections get a hint popup instead of a silent no-op."""
        extract_id = self._extract_id_for_item(self.tree.currentItem())
        if extract_id is None:
            QMessageBox.information(
                self,
                "Delete Extract",
                "Select an Extract row (or one of its image captures) to delete.",
            )
            return
        conn = self._db_conn()
        if conn is None:
            return
        reply = QMessageBox.question(
            self,
            "Delete Extract",
            f"Delete Extract #{extract_id} and all of its captures?\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            delete_extract(conn, extract_id)
            self.refresh()
