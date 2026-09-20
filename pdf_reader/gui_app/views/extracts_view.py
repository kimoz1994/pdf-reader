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
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap, QIcon

from services.extract_store import (
    delete_extract,
    list_docs_with_extracts,
    list_extracts_for_doc,
)


class ExtractsView(QWidget):
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
        self.tree.setHeaderLabels(["Extracts"])
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

        self.setLayout(layout)
        self.refresh()

    def refresh(self):
        """Reload the Document -> Extract -> Capture hierarchy."""
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
            doc_item = QTreeWidgetItem([name])
            doc_item.setData(0, Qt.ItemDataRole.UserRole, {"doc_id": doc_id})
            for extract in extracts:
                ex_item = QTreeWidgetItem(
                    [f"Extract #{extract.id} — {extract.type} "
                     f"({len(extract.captures)} capture{'s' if len(extract.captures) != 1 else ''})"]
                )
                ex_item.setData(
                    0, Qt.ItemDataRole.UserRole, {"doc_id": doc_id, "extract_id": extract.id}
                )
                for cap in extract.captures:
                    if cap.kind == "image" and cap.image_blob:
                        pix = QPixmap()
                        if pix.loadFromData(cap.image_blob):
                            icon = QIcon(
                                pix.scaled(
                                    64, 64,
                                    Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation,
                                )
                            )
                        else:
                            icon = QIcon()
                        cap_item = QTreeWidgetItem([f"🖼️ Image — page {cap.page + 1}"])
                        cap_item.setIcon(0, icon)
                    else:
                        cap_item = QTreeWidgetItem(
                            [f"🔤 Page {cap.page + 1}: {cap.text_content or ''}"]
                        )
                    ex_item.addChild(cap_item)
                doc_item.addChild(ex_item)
            doc_item.setExpanded(True)
            self.tree.addTopLevelItem(doc_item)

        self.tree.expandAll()

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