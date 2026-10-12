"""Encrypted PDFs (#116): password prompt, wrong-password warning,
cancel leaves the previous document intact."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf
import pytest
from PyQt6.QtPdf import QPdfDocument
from PyQt6.QtWidgets import QApplication, QLineEdit

from views.pdf_reader_view import PDFReaderView


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def plain_pdf(tmp_path_factory):
    path = tmp_path_factory.mktemp("pdf") / "plain.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "hello")
    doc.save(str(path))
    doc.close()
    return str(path)


@pytest.fixture(scope="module")
def encrypted_pdf(tmp_path_factory):
    path = tmp_path_factory.mktemp("pdf") / "locked.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "secret")
    doc.save(
        str(path),
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        owner_pw="owner",
        user_pw="hunter2",
    )
    doc.close()
    return str(path)


@pytest.fixture
def view(app, plain_pdf):
    v = PDFReaderView()
    v.resize(1000, 800)
    v.show()
    app.processEvents()
    yield v
    v.hide()


def test_unencrypted_needs_no_prompt(view, plain_pdf, monkeypatch):
    """(#116) A plain PDF never opens a dialog."""
    prompts = []
    monkeypatch.setattr(
        "views.pdf_reader_view.QInputDialog.getText",
        lambda *a, **k: prompts.append(1) or ("", False),
    )
    assert view._prompt_password(plain_pdf) == ""
    assert prompts == []


def test_cancel_returns_none(view, encrypted_pdf, monkeypatch):
    """(#116 AC) Cancelling the prompt returns None — load_pdf then
    returns early, previous document untouched."""
    monkeypatch.setattr(
        "views.pdf_reader_view.QInputDialog.getText",
        lambda *a, **k: ("", False),
    )
    assert view._prompt_password(encrypted_pdf) is None


def test_correct_password_accepted(view, encrypted_pdf, monkeypatch):
    """(#116 AC) The right password is returned."""
    monkeypatch.setattr(
        "views.pdf_reader_view.QInputDialog.getText",
        lambda *a, **k: ("hunter2", True),
    )
    assert view._prompt_password(encrypted_pdf) == "hunter2"


def test_wrong_password_warns_then_reprompts(view, encrypted_pdf, monkeypatch):
    """(#116 AC) A wrong password shows a clear warning and asks again;
    the second attempt succeeds."""
    attempts = [("wrong", True), ("hunter2", True)]
    warnings = []

    def fake_gettext(*a, **k):
        return attempts.pop(0)

    monkeypatch.setattr(
        "views.pdf_reader_view.QInputDialog.getText", fake_gettext
    )
    monkeypatch.setattr(
        "views.pdf_reader_view.QMessageBox.warning",
        lambda *a, **k: warnings.append(a),
    )

    assert view._prompt_password(encrypted_pdf) == "hunter2"
    assert warnings and "password" in warnings[0][2].lower()
    assert attempts == []  # both prompts consumed


def test_empty_user_password_no_prompt(view, tmp_path, monkeypatch):
    """(#116) A doc encrypted for permissions only (empty user pw)
    opens with '' and no dialog."""
    path = tmp_path / "perm.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "x")
    doc.save(str(path), encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="o")
    doc.close()
    prompts = []
    monkeypatch.setattr(
        "views.pdf_reader_view.QInputDialog.getText",
        lambda *a, **k: prompts.append(1) or ("", False),
    )
    assert view._prompt_password(str(path)) == ""
    assert prompts == []


def test_cancel_leaves_previous_document_intact(view, plain_pdf, encrypted_pdf, monkeypatch):
    """(#116 AC) Cancel during the prompt: the already-open document
    is still live and attached — no teardown happened."""
    view.load_pdf(plain_pdf)
    app = QApplication.instance()
    app.processEvents()
    first_doc = view.doc
    assert first_doc is not None and first_doc.pageCount() > 0

    monkeypatch.setattr(
        "views.pdf_reader_view.QInputDialog.getText",
        lambda *a, **k: ("", False),
    )
    view.load_pdf(encrypted_pdf)
    app.processEvents()

    assert view.doc is first_doc
    assert view.doc.pageCount() > 0
    assert view.current_pdf == plain_pdf  # not switched


def test_encrypted_load_with_password_shows_content(view, encrypted_pdf, monkeypatch):
    """(#116) Full path: prompt returns the password, load succeeds."""
    monkeypatch.setattr(
        "views.pdf_reader_view.QInputDialog.getText",
        lambda *a, **k: ("hunter2", True),
    )
    view.load_pdf(encrypted_pdf)
    QApplication.instance().processEvents()

    assert view.doc is not None
    assert view.doc.pageCount() == 1
    assert view.current_pdf == encrypted_pdf
