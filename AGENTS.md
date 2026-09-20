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

## Structure
- `gui_app/main.py` — entry point. `main_window.py` holds `MainWindow` (sidebar + view stack).
- `gui_app/views/` — screens: `library_view.py`, `pdf_reader_view.py` (core reader), plus `extracts_view.py`/`flashcards_view.py` placeholders.
- `gui_app/services/` — `search_engine.py`, `hint_overlay.py`, and relocated engine modules (`element_detector.py`, `pdf_loader.py`, `hint_generator.py`).

## Gotchas
- **Dormant code**: the hint system is not wired up. `services/hint_overlay.py` is never imported by the active GUI path; `pdf_reader_view.py` emits `hint_mode_requested` but nothing connects it. Likewise `services/search_engine.py` is dead — search is implemented inline in `pdf_reader_view.py`. Moving/refactoring these is safe, but don't assume they affect runtime.
- `services/` files use package-relative imports (`from .element_detector ...`); it has an `__init__.py`. If you activate them, import via the package, not as scripts.
- `gui_app/library.db` (per-file read progress) and `__pycache__/` are gitignored.
- `gui_app/views/pdf_reader_view.py:26-28` inserts the repo root into `sys.path` — cargo-culted; not actively required by anything.

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
- **Commit and push after every change** — the user does not want to be reminded. Feature work goes on feature branches → PR → review → merge to `master`. Doc-only changes may go straight to `master`.
- Repo `origin` is `https://github.com/kimoz1994/pdf-reader.git`. Current branch: `master` (no remote branch protection yet).
- **Live documents to keep updated**: `README.md` (repo root, follows the aishippingblog 16-section guide; not all sections apply — mark gaps honestly), `pdf_reader/README.md` (short pointer to root README), and `CONTEXT.md` (domain glossary — updated during design/grilling, not a spec).
- Planned work stream: extract workflow — PR ① capture flow (`e`/`Esc`/`d`-twice) + blue re-draw + Extracts hierarchy + delete; PR ② editing + jump-back.
