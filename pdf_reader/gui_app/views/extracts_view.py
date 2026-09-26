"""
Extracts View — browse captured material.

Shows the library's Documents, each expandable into its Extracts
(newest-first), and each Extract into its Captures (text or image).
Deleting an Extract removes it and its Captures after confirmation.
All data comes from the headless persistence seam (`services.extract_store`).
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
    QAbstractItemDelegate,
    QStyledItemDelegate,
    QHeaderView,
)
from PyQt6.QtCore import Qt, QEvent, pyqtSignal
from PyQt6.QtGui import QBrush, QColor

from services.extract_store import (
    delete_extract,
    display_title,
    list_docs_with_extracts,
    list_extracts_for_doc,
    preview_for_extract,
    update_capture_text,
)


def _cap_label(page: int, text: str) -> str:
    """Display label for a text Capture row."""
    return f"🔤 Page {page + 1}: {text}"


class _CaptureTextDelegate(QStyledItemDelegate):
    """Inline editor for text Captures.

    Enter and focus-out save, Esc cancels — handled explicitly so the
    semantics do not depend on Qt's default edit-trigger behaviour.
    """

    def __init__(self, view):
        super().__init__(view)
        self._view = view

    def createEditor(self, parent, option, index):
        editor = super().createEditor(parent, option, index)
        editor.installEventFilter(self)
        return editor

    def setEditorData(self, editor, index):
        data = self._view._edit_item_data()
        editor.setText((data or {}).get("text", ""))

    def setModelData(self, editor, model, index):
        self._view._apply_capture_edit(editor.text())

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress and event.key() in (
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
        ):
            self.setModelData(obj, None, None)
            self._close_editor(obj, QAbstractItemDelegate.EndEditHint.NoHint)
            return True
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            self._close_editor(obj, QAbstractItemDelegate.EndEditHint.RevertModelCache)
            return True
        if event.type() == QEvent.Type.FocusOut:
            if obj.property("_edit_done"):
                return True
            self.setModelData(obj, None, None)
            self._close_editor(obj, QAbstractItemDelegate.EndEditHint.NoHint)
            return True
        return super().eventFilter(obj, event)

    def _close_editor(self, editor, hint):
        editor.setProperty("_edit_done", True)
        self.closeEditor.emit(editor, hint)
        self._view._edit_item = None


class ExtractsView(QWidget):
    # Payload: {"path", "page", "rect", "extract_id"} for the first Capture
    jump_requested = pyqtSignal(dict)
    def __init__(self):
        super().__init__()
        self._edit_item = None
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

        # Editing is driven explicitly by itemActivated, never by
        # Qt's default edit triggers, so single-click never opens an editor.
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._capture_delegate = _CaptureTextDelegate(self)
        self.tree.setItemDelegateForColumn(0, self._capture_delegate)

        self.setLayout(layout)
        self.refresh()

    def refresh(self):
        """Reload the Document -> Extract -> Capture hierarchy."""
        self._edit_item = None
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
                count = len(extract.captures)
                base_label = (
                    f"Extract #{extract.id} — {extract.type} "
                    f"({count} capture{'s' if count != 1 else ''})"
                )
                ex_item = QTreeWidgetItem(
                    [f"{base_label}: {preview_for_extract(extract)}", "↱ Jump"]
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
                for cap in extract.captures:
                    if cap.kind == "image" and cap.image_blob:
                        # No thumbnail icon: at row height it was an
                        # illegible (often blank-white) rectangle.
                        cap_item = QTreeWidgetItem([f"🖼️ Image — page {cap.page + 1}"])
                    else:
                        cap_item = QTreeWidgetItem(
                            [_cap_label(cap.page, cap.text_content or "")]
                        )
                        # Text Captures are editable; image rows are not.
                        cap_item.setFlags(cap_item.flags() | Qt.ItemFlag.ItemIsEditable)
                    cap_item.setData(
                        0, Qt.ItemDataRole.UserRole,
                        {
                            "capture_id": cap.id,
                            "kind": cap.kind,
                            "page": cap.page,
                            "text": cap.text_content or "",
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
        """Enter/double-click: edit a text Capture, jump from an Extract row."""
        data = item.data(0, Qt.ItemDataRole.UserRole) or {}
        if data.get("kind") == "text" and data.get("capture_id") is not None:
            self._begin_capture_edit(item)
            return
        self._jump_from_item(item)

    def _begin_capture_edit(self, item):
        """Open the inline editor on a text Capture row."""
        if self._edit_item is not None:
            return
        self._edit_item = item
        self.tree.editItem(item, 0)

    def _edit_item_data(self):
        if self._edit_item is None:
            return None
        return self._edit_item.data(0, Qt.ItemDataRole.UserRole) or {}

    def _apply_capture_edit(self, new_text: str):
        """Persist an inline edit; empty/whitespace edits are rejected by the
        store and leave both the row and the displayed label untouched."""
        item = self._edit_item
        if item is None:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole) or {}
        capture_id = data.get("capture_id")
        conn = self._db_conn()
        if capture_id is None or conn is None:
            return
        if update_capture_text(conn, capture_id, new_text):
            data["text"] = new_text
            item.setData(0, Qt.ItemDataRole.UserRole, data)
            item.setText(0, _cap_label(data["page"], new_text))

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