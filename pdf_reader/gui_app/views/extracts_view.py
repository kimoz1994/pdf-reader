"""
Extracts View — browse captured material.

Shows the library's Documents, each expandable into its Extracts
(newest-first), and each Extract into its image Captures. Activating a
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
)
from PyQt6.QtCore import Qt, QItemSelectionModel, QUrl, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QImage,
    QTextCursor,
    QTextDocument,
    QTextImageFormat,
    QTextOption,
)

from services.extract_store import (
    IMG_PLACEHOLDER,
    delete_extract,
    display_title,
    list_docs_with_extracts,
    list_extracts_for_doc,
    preview_for_extract,
    save_extract_text,
)


def _extract_label(extract) -> str:
    """Tree row label: identity + live content preview."""
    count = len(extract.captures)
    base = (
        f"Extract #{extract.id} — {extract.type} "
        f"({count} capture{'s' if count != 1 else ''})"
    )
    return f"{base}: {preview_for_extract(extract)}"


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
                font-size: 15px;
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
        back_row.addStretch()
        ed.addLayout(back_row)

        self.editor_title = QLabel()
        self.editor_title.setStyleSheet(
            "font-size: 22px; font-weight: bold; color: #3498db;"
        )
        ed.addWidget(self.editor_title)

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
        """Reload the Document -> Extract -> Capture hierarchy."""
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
            if not Path(path).exists():
                continue
            extracts = list_extracts_for_doc(conn, doc_id)
            rows.append((name, path, doc_id, extracts))

        if not rows:
            self.empty_label.show()
            self.tree.hide()
            return
        self.empty_label.hide()
        self.tree.show()

        for name, path, doc_id, extracts in rows:
            doc_item = QTreeWidgetItem([display_title(path, name)])
            doc_item.setData(0, Qt.ItemDataRole.UserRole, {"doc_id": doc_id})
            for extract in extracts:
                first_cap = extract.captures[0] if extract.captures else None
                ex_item = QTreeWidgetItem([_extract_label(extract), "↱ Jump"])
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
                for cap in extract.captures:
                    if cap.kind != "image" or not cap.image_blob:
                        continue
                    # No thumbnail icon: at row height it was an
                    # illegible (often blank-white) rectangle. Text
                    # captures get no rows — the blob preview on the
                    # Extract row is their single source of truth.
                    cap_item = QTreeWidgetItem([f"🖼️ Image — page {cap.page + 1}"])
                    cap_item.setData(
                        0, Qt.ItemDataRole.UserRole,
                        {
                            "capture_id": cap.id,
                            "kind": cap.kind,
                            "page": cap.page,
                        },
                    )
                    ex_item.addChild(cap_item)
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
        """Enter/double-click: the ↱ column still jumps; every other row
        (Extract or image Capture) opens the full-area Extract Editor."""
        if column == 1:
            self._jump_from_item(item)
            return
        self._open_editor(item)

    def _open_editor(self, item):
        """Open the editor for the Extract owning `item` — either the
        Extract row itself or one of its image Capture rows. Document
        rows are a no-op (they own no single Extract)."""
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
        order."""
        blob = extract.text_content or ""
        images = [c for c in extract.captures if c.kind == "image" and c.image_blob]
        parts = blob.split(IMG_PLACEHOLDER)
        cursor = edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        for i, part in enumerate(parts):
            if part:
                cursor.insertText(part)
            if i < len(images):
                cursor.insertImage(self._image_format(edit.document(), images[i], i))

    def _image_format(self, doc, cap, index):
        """Inline image format for one Capture: decoded PNG registered as
        a document resource, scaled down to at most 720px wide."""
        image = QImage.fromData(cap.image_blob)
        if not image.isNull() and image.width() > 720:
            image = image.scaledToWidth(
                720, Qt.TransformationMode.SmoothTransformation
            )
        url = f"capimg://{index}"
        doc.addResource(QTextDocument.ResourceType.ImageResource, QUrl(url), image)
        fmt = QTextImageFormat()
        fmt.setName(url)
        if not image.isNull():
            fmt.setWidth(float(image.width()))
            fmt.setHeight(float(image.height()))
        return fmt

    def _mark_dirty(self):
        """The document changed: enable Save (Back would auto-save anyway)."""
        self._editor_dirty = True
        self.save_btn.setEnabled(True)

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
        if not save_extract_text(
            conn, self._editor_extract_id, self._editor_doc_edit.toPlainText()
        ):
            return False
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
        self.save_btn.setEnabled(False)
        self.tree.setFocus()

    def _jump_from_item(self, item):
        data = item.data(0, Qt.ItemDataRole.UserRole) or {}
        if data.get("page") is None or not data.get("path"):
            return
        self.jump_requested.emit(dict(data))

    def delete_selected(self):
        """Delete the selected Extract after a confirmation popup."""
        item = self.tree.currentItem()
        if item is None:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole) or {}
        extract_id = data.get("extract_id")
        if extract_id is None:
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
