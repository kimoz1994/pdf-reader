# AGENTS.md

GUI-only PyQt6 PDF reader (console version was removed). Educational/experimental project.

## Run the app
Use the helper scripts from the repo root (they pick the `pdf-reader-clean` env python and `gui_app/` working dir automatically):

```powershell
.\run.ps1   # run once
.\dev.ps1   # watch gui_app/**/*.py and auto-restart on save
```

Manual equivalent (imports are flat, not `gui_app.`-prefixed, so run from `gui_app/`):

```powershell
cd pdf_reader/gui_app
python main.py
```

- Environment python: `D:\volume\tempprograms\anaconda\envs\pdf-reader-clean\python.exe` (conda env `pdf-reader-clean`).
- Dependencies: `PyQt6` + `pymupdf`, declared in `requirements.txt` (repo root). A fresh environment will fail to import until deps are installed (e.g. `pip install -r requirements.txt`).
- Image/PDF lib is imported as `pymupdf` in the GUI code, not `fitz` (though `services/*` loader/detector still use `fitz`).

## Testing
Run the pytest suite from `pdf_reader/gui_app` (flat imports, same as the app):

```powershell
cd pdf_reader/gui_app
$env:PYTHONNOUSERSITE="1"; & "D:\volume\tempprograms\anaconda\envs\pdf-reader-clean\Scripts\pytest.exe" tests/
```

- Deps: `pytest` (in `requirements-dev.txt`). The suite covers the two headless seams in `services/`: `test_extract_store.py` (extract/capture SQL against a temp SQLite DB, no Qt) and `test_pdf_geometry.py` (page-layout math mirroring Qt's `calculateDocumentLayout`).
- The GUI view (`pdf_reader_view.py`) has no automated tests; verify drag→`e`→blue, click→image capture, and `d`-twice delete manually via `run.ps1`. Smoke-testing the reader offscreen works but offscreen Qt probe scripts may crash at teardown after writing results (harmless; read the output file).
- `library.db` is gitignored — never commit it. If a smoke test left test rows, clear them: delete `captures`/`extracts`, and any `pdfs` row pointing at `test.pdf`.

## Structure
- `gui_app/main.py` — entry point. `main_window.py` holds `MainWindow` (sidebar + view stack).
- `gui_app/views/` — screens: `library_view.py`, `pdf_reader_view.py` (core reader), `extracts_view.py` (Document→Extract review + edit + delete, one row per Extract; the full-area Extract Editor), plus `flashcards_view.py` placeholder.
- `gui_app/services/` — headless seams `extract_store.py` (extract/capture SQL, no Qt) and `pdf_geometry.py` (Qt-mirroring layout math); plus dormant modules `search_engine.py`, `hint_overlay.py`, and relocated engine modules (`element_detector.py`, `pdf_loader.py`, `hint_generator.py`).
- `gui_app/tests/` — pytest suite for the two seams (flat imports via `conftest.py`).

## Gotchas
- **Dormant code**: the hint system is not wired up. `services/hint_overlay.py` is never imported by the active GUI path; `pdf_reader_view.py` emits `hint_mode_requested` but nothing connects it. Likewise `services/search_engine.py` is dead — search is implemented inline in `pdf_reader_view.py`. `element_detector.py` (used for image click-capture) is now live in the reader path, but `pdf_loader.py` and `hint_generator.py` stay dormant. Moving/refactoring these is safe.
- `services/` files use package-relative imports (`from .element_detector ...`); it has an `__init__.py`. If you activate them, import via the package, not as scripts. (`extract_store.py` and `pdf_geometry.py` are flat — imported as `services.extract_store` from the app/tests.)
- `gui_app/library.db` (per-file read progress) and `__pycache__/` are gitignored.
- `gui_app/views/pdf_reader_view.py:26-28` inserts the repo root into `sys.path` — cargo-culted; not actively required by anything.
- Extracts schema (blob model): `extracts(id, doc_id, created_at, type, text_content)` + `captures(id, extract_id, page, rect 'x0,y0,x1,y1' - both nullable, NULL for pasted images #48, kind, text_content, image_blob, display_w, display_order)` — the Extract's text is ONE blob in `text_content` (inline images marked U+FFFC, one per image Capture in capture order); captures are immutable anchors (their `text_content` is always NULL; `display_w`/`display_order` are presentation-only — inline-image resize width (#37) and capture order in the blob: text anchors first, then images in document order (#48)) used for blue redraw + Jump. The reader draws persisted extracts blue on load and keeps a transient yellow Working Set; commiting (`e`) turns the Working Set into one Extract row (blob joined blank-line-separated, placeholders per image); `d`-twice deletes the newest Extract on the current page; the Extracts View (Document→Extract, one row per Extract) reviews and edits (the full-area Extract Editor: ONE joined `_ExtractDocEdit` per Extract with inline images - including clipboard image pastes (#48: stored on save as page/rect-NULL captures) - 💾 Save + Back auto-save through `save_extract_text` (legacy text-only path returns `True`; with image backends it returns the created paste ids or `False`) which strips unbacked placeholders — a deleted placeholder stays deleted, empties allowed) and deletes with a confirmation popup. `capture_overlaps_extract` / `delete_extract` / `save_extract_text` live in the seam; `init_schema` is idempotent AND migrates older DBs once (backfills the blob from legacy per-capture text then NULLs it; atomically rewrites `captures` for nullable `page`/`rect` + `display_order`, #48).

## Skills
- Project-local skills live in `.opencode/skills/` (one subfolder per skill, each with a `SKILL.md`). This folder is gitignored (personal, not app files). A restart of the opencode session is required to pick up new/edited skills.
- All skills (including the Matt Pocock workflow skills) are project-scoped only — none are installed globally.

## Agent skills
### Issue tracker
Issues and specs are tracked in GitHub Issues (`gh` CLI). See `docs/agents/issue-tracker.md`.
### Triage labels
Default five canonical role labels used as-is. See `docs/agents/triage-labels.md`.
### Domain docs
Single-context: one `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.

## Workflow (user expectation)
- **Commit and push after every change** — the user does not want to be reminded. Feature work goes on feature branches → PR → review → merge to `master`. Doc-only changes go straight to `master`, and `AGENTS.md` itself is edited directly on `master` (self-referential doc).
- Repo `origin` is `https://github.com/kimoz1994/pdf-reader.git`. Current branch: `master` (no remote branch protection yet).
- **Live documents to keep updated**: `README.md` (repo root, follows the aishippingblog 16-section guide; not all sections apply — mark gaps honestly), `HOW_TO_USE.md` (repo root — user-facing, example-driven feature guide; whenever a feature ships, document it there and clear it from the "Not available yet" list), `pdf_reader/README.md` (short pointer to root README), and `CONTEXT.md` (domain glossary — updated during design/grilling, not a spec). Docs are not deferred to a ticket: keep them true at every merge.
- Extract workflow **shipped** (spec #22, closed): capture flow (`e`/`Esc`/`d`-twice) + blue re-draw + Extracts hierarchy + delete (PR ① era, #18), row previews (#23), Extract Editor read (#24) + editing (#25), reader back-nav (#28, superseding #13). Next open backlog: #17 (orphaned extracts), flashcards, packaging.
