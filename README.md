# PDF Reader

A desktop PDF reader for studying: read documents in a keyboard-driven reader, extract highlights into notes, and review them later.

It helps people who read PDFs for learning — course materials, papers, and technical docs — capture what matters without leaving the reading flow. Select text (drag) or an image (click), press `e`, and it becomes a persistent extract you can review and delete from the reader or the dedicated Extracts view.

## Demo

*Work in progress — screenshots will be added once the full extract workflow lands.*

The core reader is already usable: open a PDF from the library, navigate with Vim-style keys (`j`/`k`, `gg`/`G`, `space`), search with `/`, and zoom with `+`/`-`. Read progress (last page) is remembered per file.

The capture workflow is in: drag over text (or click a detected image) to build a transient yellow **Working Set** (non-contiguous selections stack), press `e` to persist it as a single **Extract**, which re-draws in transparent **blue** and survives restarts (stored in `library.db`). `Esc` clears the Working Set without persisting. Press `d` twice to delete the newest Extract on the current page, or review/delete everything from the **Extracts** view (Documents → Extracts → Captures, newest-first).

## Problem

- People who study from PDFs want to remember what they read, but most readers make capturing notes a side task with its own workflow.
- Extracting an interesting figure, a quote, or a formula usually means a second application (copy, switch windows, paste into notes) or a separate annotation layer that is hard to browse afterwards.
- Generic note tools lose the link to the source page; PDF-native tools bury the notes inside the document.

This project is a study workflow: select, extract, review — in one place, keyboard-first, without leaving the reader.

## Evaluation

Not applicable yet. This is a desktop GUI application; the primary "performance" question is whether the extract flow feels fast enough to use while reading, which we will evaluate by usage rather than offline metrics. To be added after the extract feature ships.

## Testing

The two headless seams in `gui_app/services/` have a pytest suite: `tests/test_extract_store.py` (extract/capture SQL against a temp SQLite DB, no Qt) and `tests/test_pdf_geometry.py` (layout math mirroring Qt's `calculateDocumentLayout`).

```powershell
cd pdf_reader/gui_app
$env:PYTHONNOUSERSITE="1"; & "D:\volume\tempprograms\anaconda\envs\pdf-reader-clean\Scripts\pytest.exe" tests/
```

Deps: `pytest` is in `requirements-dev.txt`. The GUI itself (`pdf_reader_view.py`) is verified manually against `pdf_reader/pdfs/test.pdf`: drag → yellow → `e` → blue, `Esc` clears, blue re-draws on reopen, click an image → yellow → `e` → blue, `d`-twice deletes, and the Extracts view lists/deletes.

## Monitoring

Not applicable — the app runs locally with no external services. Usage data (read progress, extracts) is stored in a local SQLite database (`pdf_reader/gui_app/library.db`).

## Quickstart

Prerequisites:

- Python 3.11+
- Conda or another environment manager (recommended)
- The dependencies in `requirements.txt` (`PyQt6`, `pymupdf`)

Install:

```bash
pip install -r requirements.txt
```

Run:

```powershell
.\run.ps1
```

`run.ps1` and `dev.ps1` pick the `pdf-reader-clean` conda environment's Python automatically. `dev.ps1` watches the `gui_app/` sources and auto-restarts the app on every save — use it while developing.

Manual run (imports are flat, so run from the `gui_app/` directory):

```powershell
cd pdf_reader/gui_app
python main.py
```

## Data and configuration

No environment variables or API keys are required. The app creates `pdf_reader/gui_app/library.db` (SQLite) on first run to store library entries, per-file read progress, and extracted notes (`extracts` + `captures` tables).

`test.pdf` in `pdf_reader/pdfs/` is a sample document for trying the reader without hunting for a PDF.

## Deployment

Not deployed — it is a local desktop application. Packaging into a standalone installer is planned future work (see Future work).

## Architecture

```
MainWindow
│  (sidebar + view stack)
├── LibraryView       lists documents, opens a PDF
├── PdfReaderView     QPdfView-based reader (keys, search, page progress, extraction)
├── ExtractsView      Documents → Extracts → Captures review + delete
└── FlashcardsView    placeholder

services/             engine modules (element detection, PDF loading, hints)
                       — element_detector is live (image click-capture), the rest dormant
services/extract_store.py   headless extract/capture SQL seam (no Qt), pytest-tested
services/pdf_geometry.py    layout/mapping math mirroring Qt's calculateDocumentLayout
```

The reader renders pages through QtPdf (`QPdfView`); PyMuPDF is used for text search, image element detection (for click-capture), and image blob rendering; `QPdfDocument.getSelection` supplies the text payload for drag-captures. Highlight rects are computed by a Qt-mirroring layout model (`pdf_geometry.py`) so yellow/blue rects stay aligned with the rendered pages.

## Project structure

```
pdf_reader/
├── requirements.txt          pinned runtime dependencies
├── requirements-dev.txt      dev/test deps (pytest)
├── run.ps1 / dev.ps1         run once / auto-restart while developing
├── CONTEXT.md                domain vocabulary for the extract feature
├── pdf_reader/
│   ├── gui_app/
│   │   ├── main.py           entry point
│   │   ├── main_window.py    sidebar + view routing
│   │   ├── sidebar.py
│   │   ├── services/
│   │   │   ├── extract_store.py   headless extract/capture SQL seam (no Qt)
│   │   │   ├── pdf_geometry.py    Qt-mirroring layout/mapping math
│   │   │   ├── element_detector.py  live — image click-capture in the reader
│   │   │   └── (dormant) pdf_loader, hint_generator, hint_overlay, search_engine
│   │   ├── tests/            pytest (test_extract_store, test_pdf_geometry)
│   │   └── views/
│   │       ├── library_view.py
│   │       ├── pdf_reader_view.py   the core reader
│   │       ├── extracts_view.py     Documents → Extracts → Captures + delete
│   │       └── flashcards_view.py   placeholder
│   └── pdfs/test.pdf         sample document
```

## Decisions and trade-offs

- **PyQt6 over Tkinter / a web app** — native desktop widgets and QtPdf integration; accepted cost: a heavier dependency.
- **QtPdf for page rendering + PyMuPDF for search/extraction** — best of both: native rendering with fast text searching via PyMuPDF's page-space rects.
- **SQLite for storage** — no server, single file, adequate for a local single-user app.
- **Flat imports in `gui_app/`** — the app currently runs from `gui_app/` rather than as an installed package; keeps the entry point trivial at the cost of a less conventional import style.

## CI/CD

None. The project is developed locally with git-only workflow (feature branches + PRs). Adding CI (lint + smoke test) is planned.

## Limitations

- The GUI view (`pdf_reader_view.py`) has no automated tests — drag→`e`→blue, image click-capture, and `d`-twice delete are verified manually; only the headless seams are pytest-covered.
- The hint system (`services/hint_overlay.py`, `hint_generator.py`) and the search engine (`services/search_engine.py`) exist but are not wired into the running app — search is implemented inline in the reader view.
- Editing captures and jump-back from the Extracts view are not done.
- Re-highlighting already-extracted (blue) content is refused with a status hint — per the domain rule "yellow is never drawn over blue".
- No packaging/installer yet; requires a Python environment.

## Future work

1. Editing text captures + jump-back from the Extracts view.
2. Flashcard review from extracts.
3. Standalone packaging (e.g. PyInstaller), CI with lint + smoke checks.

## Self-evaluation

This is a learning project (AI Dev Zoomcamp). Current status against the course rubric, to be revisited as features land: problem statement — covered (above); implementation — reader functional, full capture workflow shipped (drag/click → `e` → blue, `d`-twice delete, Extracts view); testing — headless seams pytest-covered, GUI verified manually; monitoring — not applicable (local app); documented as gaps rather than silent.

---

## How this README was built

Follows the 16-section guidance from Alexey Grigorev's [How to Write a Good README](https://aishippingblog.com/p/how-to-write-a-good-readme). Sections that do not apply yet (evaluation, monitoring, CI/CD) are stated honestly instead of omitted, per the article's advice.