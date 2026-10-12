# PDF Reader

A desktop PDF reader for studying: read documents in a keyboard-driven reader, extract highlights into notes, and review them later.

It helps people who read PDFs for learning — course materials, papers, and technical docs — capture what matters without leaving the reading flow. Select text (drag) or an image (click), press `e`, and it becomes a persistent extract you can review and delete from the reader or the dedicated Extracts view. Turn any passage into a flashcard and drill it with an Anki-style spaced-repetition session (FSRS).

**New here? Start with the [How to Use guide](HOW_TO_USE.md)** — a guided, example-driven tour of every feature.

## Demo

*Work in progress — screenshots are pending.*

The core reader is already usable: open a PDF from the library, navigate with Vim-style keys (`j`/`k`, `gg`/`G`, `space`), search with `/`, and zoom with `+`/`-`. Read progress (last page) is remembered per file.

The capture workflow is in: drag over text (or click a detected image) to build a transient yellow **Working Set** (non-contiguous selections stack), press `e` to persist it as a single **Extract**, which re-draws in transparent **blue** and survives restarts (stored in `library.db`). `Esc` clears the Working Set without persisting. Press `d` twice to delete the newest Extract on the current page, or review/delete everything from the **Extracts** view (Documents → Extracts → Captures, newest-first, each Extract row previewing its content). Select an Extract — or any capture inside it — and press `Enter` (or double-click) to open the full-area **Extract Editor**, which shows the whole group as ONE continuous document you can type into — text and inline images together, one cursor across all captures (**💾 Save** persists mid-session; `← Back` auto-saves and returns to the tree). **↱ Jump** (click) reopens the reader centered on the original region with a brief orange flash.

## Problem

- People who study from PDFs want to remember what they read, but most readers make capturing notes a side task with its own workflow.
- Extracting an interesting figure, a quote, or a formula usually means a second application (copy, switch windows, paste into notes) or a separate annotation layer that is hard to browse afterwards.
- Generic note tools lose the link to the source page; PDF-native tools bury the notes inside the document.

This project is a study workflow: select, extract, review — in one place, keyboard-first, without leaving the reader.

## Evaluation

Shipped as the snappiness round (#87–#94, PRs #90–#96): scroll, open, Back and reopen were each diagnosed, fixed and measured with an opt-in timing log (`PDFR_DEBUG_PERF=1` or a `perf.enabled` marker file → console + `pdf_reader/gui_app/perf.log`, including the perceived-latency line `back: click -> library first paint`). Highlights on the dev machine: cold open 756 → ~290 ms, same-file reopen ~400+ → ~5 ms, Back click → first paint ~8–11 ms. Continue to evaluate by feel in real use — with the log on, every Back click records its real latency in `perf.log`.

## Testing

The seams in `gui_app/services/` and the offscreen-capable Qt views have a pytest suite (~217 tests): extract/capture/flashcard SQL and DB backup against a temp SQLite DB, layout math, editor-selection snapshots, the FSRS scheduler, the review-session loop, card-list/due-filter behavior, the Extracts-view jump landing, library-list UX (checkbox removal, backup, Back rebuild-skip, row-click no-op), tree/flashcard label helpers, reader search keys, and the reader's open/reopen seams (extract load once, fast-reopen identity). CI (`.github/workflows/tests.yml`) runs the whole suite on every push to `master` and every PR (ubuntu-latest, Python 3.12, `QT_QPA_PLATFORM=offscreen`, #81).

```powershell
cd pdf_reader/gui_app
$env:PYTHONNOUSERSITE="1"; & "D:\volume\tempprograms\anaconda\envs\pdf-reader-clean\Scripts\pytest.exe" tests/
```

Deps: `pytest` is in `requirements-dev.txt`. The core reader (`pdf_reader_view.py`) is verified manually against `pdf_reader/pdfs/test.pdf`: drag → yellow → `e` → blue, `Esc` clears, blue re-draws on reopen, click an image → yellow → `e` → blue, `d`-twice deletes, and ↱ Jump reopens the reader centered on the region; only its search behavior (keys/highlight) is pytest-covered. The Extracts view's list/delete flow and the Extract Editor's edit loop (type, Save, Back auto-saves) are likewise manual — only the view's `open_extract` jump landing has widget tests.

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

Not deployed — it is a local desktop application. For running it **without a Python environment**, the repo ships a PyInstaller build (#118):

### Running without Python (standalone build)

Build steps (Windows, from the repo root):

```powershell
# 1. One-time: install deps + PyInstaller into the app's environment
pip install -r requirements.txt -r requirements-dev.txt

# 2. Build (produces dist/pdf_reader/pdf_reader.exe, ~1-2 min)
python -m PyInstaller --noconfirm pdf_reader.spec

# 3. Smoke-run the result
.\dist\pdf_reader\pdf_reader.exe
```

Notes:

- The spec (`pdf_reader.spec`) collects QtPdf (`PyQt6.QtPdf` — PyInstaller's static analysis doesn't always trace it) and PyMuPDF submodules; windowed (`console=False`) build.
- In the built app, `library.db` and `backups/` live **next to `pdf_reader.exe`** (not inside `_internal/`, which an upgrade replaces).
- Distribute the whole `dist/pdf_reader/` folder — the exe is not self-contained in one file. Zipping that folder is the simplest way to share it.
- No installer/signing yet; this is a manual build. CI does not build it.

## Architecture

```
MainWindow
│  (sidebar + view stack)
├── LibraryView       lists documents, opens a PDF
├── PdfReaderView     QPdfView-based reader (keys, search, page progress, extraction)
├── ExtractsView      Documents → Extracts → Captures review + edit + delete
└── FlashcardsView    card list + FSRS review session: Review (n) → question → reveal → grade 1-4 (Again re-queues, summary)

services/             engine module (element detection for image click-capture)
services/extract_store.py   headless extract/capture/flashcard SQL seam (no Qt), pytest-tested
services/selection_snapshot.py  editor selection → answer snapshot seam (offscreen Qt), pytest-tested
services/fsrs_scheduler.py  FSRS scheduling seam over the pinned `fsrs` lib (fuzz on in app, off in tests), pytest-tested
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
│   │   ├── services/
│   │   │   ├── extract_store.py   headless extract/capture/flashcard SQL seam (no Qt)
│   │   │   ├── selection_snapshot.py  editor selection → answer snapshot (offscreen Qt)
│   │   │   ├── pdf_geometry.py    Qt-mirroring layout/mapping math
│   │   │   └── element_detector.py  image click-capture in the reader
│   │   ├── tests/            pytest — full suite in AGENTS.md's Testing section (seams + offscreen Qt views)
│   │   └── views/
│   │       ├── library_view.py
│   │       ├── pdf_reader_view.py   the core reader
│   │       ├── extracts_view.py     Documents → Extracts → Captures + edit + delete
│   │       └── flashcards_view.py   card list + FSRS review session
│   └── pdfs/test.pdf         sample document
```

## Decisions and trade-offs

- **PyQt6 over Tkinter / a web app** — native desktop widgets and QtPdf integration; accepted cost: a heavier dependency.
- **QtPdf for page rendering + PyMuPDF for search/extraction** — best of both: native rendering with fast text searching via PyMuPDF's page-space rects.
- **SQLite for storage** — no server, single file, adequate for a local single-user app.
- **Flat imports in `gui_app/`** — the app currently runs from `gui_app/` rather than as an installed package; keeps the entry point trivial at the cost of a less conventional import style.

## CI/CD

None. The project is developed locally with git-only workflow (feature branches + PRs). CI runs the full pytest suite on every push to master and every pull request via GitHub Actions (`QT_QPA_PLATFORM=offscreen` on ubuntu-latest, #81). Adding lint on top is still planned.

## Limitations

- The core reader view (`pdf_reader_view.py`) is mostly verified manually — drag→`e`→blue, image click-capture, and `d`-twice delete are checked by hand; only its search behavior (keys/highlight, `test_pdf_search.py`) is pytest-covered. Right-click context menus are a further manual-only corner: offscreen Qt (used by CI) cannot deliver them.
- Re-highlighting already-extracted (blue) content is refused with a status hint — per the domain rule "yellow is never drawn over blue".
- No installer yet — the standalone build (#118) is a PyInstaller folder (`dist/pdf_reader/`) you build by hand; the dev workflow still requires a Python environment.

## Future work

1. Flashcards: creation, listing, and the FSRS review session shipped (#55/#56/#57/#58), including session completion behaviors — Again re-queue within a fixed total, "n of m" progress, end-of-session summary, "No cards due today" hint (#59) — list row actions — edit question / delete card with confirmation (#60) — the All ⇄ Due-today list toggle that shows exactly the Review session's set (#61) — and the source jump: clicking a card's Source cell opens its Extract in the Extract Editor, while cards orphaned by source deletion survive marked `⚠ source gone` with the jump hidden, no cascade (#62). The user guide now includes a worked create → review walkthrough (#63).
2. Standalone packaging shipped (#118): a PyInstaller spec builds a Windows `.exe` (see Deployment); an installer, code signing, and CI-built artifacts are still open, as is lint on top of the existing CI.
3. Data safety: one-click backup of `library.db` shipped (#83) — the `💾 Backup` button snapshots the DB (extracts, flashcards, schedules) into `backups/`, pruning to the newest 10 copies.

## Self-evaluation

This is a learning project (AI Dev Zoomcamp). Current status against the course rubric, to be revisited as features land: problem statement — covered (above); implementation — reader functional, full capture workflow shipped (drag/click → `e` → blue, `d`-twice delete, Extracts view, Extract Editor with read + edit, jump-back with centering flash); testing — seams and offscreen-capable views pytest-covered (~190 tests + CI), core reader verified manually; monitoring — not applicable (local app); documented as gaps rather than silent.

---

## How this README was built

Follows the 16-section guidance from Alexey Grigorev's [How to Write a Good README](https://aishippingblog.com/p/how-to-write-a-good-readme). Sections that do not apply yet (evaluation, monitoring, CI/CD) are stated honestly instead of omitted, per the article's advice.