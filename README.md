# PDF Reader

A desktop PDF reader for studying: read documents in a keyboard-driven reader, extract highlights into notes, and review them later.

It helps people who read PDFs for learning — course materials, papers, and technical docs — capture what matters without leaving the reading flow. Select text or an image, press `e`, and it becomes a persistent extract you can edit and review in a dedicated Extracts view.

## Demo

*Work in progress — screenshots will be added once the extract feature lands.*

The core reader is already usable: open a PDF from the library, navigate with Vim-style keys (`j`/`k`, `gg`/`G`, `space`), search with `/`, and zoom with `+`/`-`. Read progress (last page) is remembered per file.

## Problem

- People who study from PDFs want to remember what they read, but most readers make capturing notes a side task with its own workflow.
- Extracting an interesting figure, a quote, or a formula usually means a second application (copy, switch windows, paste into notes) or a separate annotation layer that is hard to browse afterwards.
- Generic note tools lose the link to the source page; PDF-native tools bury the notes inside the document.

This project is a study workflow: select, extract, review — in one place, keyboard-first, without leaving the reader.

## Evaluation

Not applicable yet. This is a desktop GUI application; the primary "performance" question is whether the extract flow feels fast enough to use while reading, which we will evaluate by usage rather than offline metrics. To be added after the extract feature ships.

## Testing

No automated tests yet. The app is verified manually after each change using a small test PDF (`pdf_reader/pdfs/test.pdf`). Adding a test suite is planned future work (see Limitations).

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

No environment variables or API keys are required. The app creates `pdf_reader/gui_app/library.db` (SQLite) on first run to store library entries, per-file read progress, and — once the extract feature ships — the extracted notes.

`test.pdf` in `pdf_reader/pdfs/` is a sample document for trying the reader without hunting for a PDF.

## Deployment

Not deployed — it is a local desktop application. Packaging into a standalone installer is planned future work (see Future work).

## Architecture

```
MainWindow
│  (sidebar + view stack)
├── LibraryView       lists documents, opens a PDF
├── PdfReaderView     QPdfView-based reader (keys, search, page progress)
├── ExtractsView      placeholder → will list/edit extracts per document
└── FlashcardsView    placeholder

services/             engine modules (element detection, PDF loading, hints)
                       — most are dormant, not wired into the GUI yet
```

The reader renders pages through QtPdf (`QPdfView`); PyMuPDF is used for text search and (planned) for extracting highlighted regions.

## Project structure

```
pdf_reader/
├── requirements.txt          pinned runtime dependencies
├── run.ps1 / dev.ps1         run once / auto-restart while developing
├── CONTEXT.md                domain vocabulary for the extract feature
├── pdf_reader/
│   ├── gui_app/
│   │   ├── main.py           entry point
│   │   ├── main_window.py    sidebar + view routing
│   │   ├── sidebar.py
│   │   └── views/
│   │       ├── library_view.py
│   │       ├── pdf_reader_view.py   the core reader
│   │       ├── extracts_view.py     placeholder
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

- No automated tests.
- The hint system (`services/hint_overlay.py`, `hint_generator.py`, `element_detector.py`) and the search engine (`services/search_engine.py`) exist but are not wired into the running app — search is implemented inline in the reader view.
- The Extracts and Flashcards views are placeholders; the extract-capture workflow is the active workstream.
- No packaging/installer yet; requires a Python environment.

## Future work

1. Extract workflow (in progress): select text/images → `e` to persist → hierarchy list in Extracts view → edit text → delete.
2. Flashcard review from extracts.
3. Automated test suite.
4. Standalone packaging (e.g. PyInstaller).
5. CI with lint + smoke checks.

## Self-evaluation

This is a learning project (AI Dev Zoomcamp). Current status against the course rubric, to be revisited as features land: problem statement — covered (above); implementation — reader functional, extract workflow planned; testing/monitoring — not yet present; documented as gaps rather than silent.

---

## How this README was built

Follows the 16-section guidance from Alexey Grigorev's [How to Write a Good README](https://aishippingblog.com/p/how-to-write-a-good-readme). Sections that do not apply yet (evaluation, monitoring, CI/CD) are stated honestly instead of omitted, per the article's advice.