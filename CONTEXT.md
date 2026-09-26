# CONTEXT.md

Domain vocabulary for the PDF reader. This is a glossary, not a spec.

## Concepts

### Document
A PDF file added to the library. Persisted in `library.db`. Has a path, a name, a page count, and a last-opened page (read progress). A document contains **Extracts**.

### Highlight
The transient yellow marking drawn over PDF content (text or image) that the user has selected **but not yet extracted**. Exists only inside the reader session. Has no persistence of its own.

Rendering rule: `yellow` while selected/un-extracted.

Highlights **accumulate**: the user may stack several non-contiguous selections (text and/or images). Pressing `e` commits the whole pending set at once.

### Working Set (pending highlights)
The reader-session buffer of accumulated Highlights awaiting commit. Purely transient; cleared — becoming an Extract — when the user presses `e`. One Highlight becomes one Capture in the resulting Extract. Not persisted across app restarts.

### Extract
A captured working set committed with the `e` key: a persisted artifact attached to a Document and bound to source locations (page, and for future jump-back, the region). Types are `text`, `image`, or `combined` (a working set containing text and/or image). Rendered `blue` in the reader.
_Avoid_: group, extracted group (informal speech for the same thing — one Extract, many Captures).

Rendering rule: `blue` once extracted.

Note the shift: a Highlight *becomes* an Extract — they are the same PDF region at two life stages (transient yellow → persisted blue), not two different kinds of thing.

### Capture
An individual snippet inside an Extract (one text region or one image region). An Extract is composed of one or more Captures taken together.

### Extracts View
The screen where the user reviews extracted material. Shows a hierarchical list: the library's **Documents**, each expandable (`+`) into its **Extracts** (each row previewing a snippet of its content). Opening an Extract replaces the list with the **Extract Editor**; closing it returns to the list.

### Extract Editor
The full-area editing surface for one Extract: a Word-like document showing every Capture of that Extract **interleaved in capture order** — editable plain text segments and read-only images side by side. Capture boundaries are fixed (text is edited within a segment; images are immutable). Saving is implicit: leaving the Editor (Back) persists the content. Images can never be edited here — only viewed with their text.
_Avoid_: inline editor (retired), rich text (formatting is out of scope for now).

### Un-extract
The act of deleting an Extract from the reader (`d`) or deleting it in the Extracts View. **Irreversible** — there is no undo and no soft delete in either view. Both paths show a confirmation prompt before the delete happens.

### Clear (Working Set)
Dismissing all pending Highlights (`Esc`) without committing anything. The Working Set is also cleared whenever the reader changes document or the document is closed — per-session, never global.

## Rules
- Delete is whole-Extract only; a Capture cannot be removed on its own.
- Image Captures are immutable (cannot be edited, only deleted as part of the Extract).
- **Editing a text Capture replaces the stored content** — the Extract becomes the user's version; the exact original quote is not kept alongside.
- Extracts are always drawn in the reader as transparent blue regions when the document is open (equivalent to how yellow highlight is shown in common PDF readers).
- Extracts are listed newest-first in the Extracts View.
- **Extracts aim to be independent of the PDF** — image data is stored in the DB (blob), not referenced, so left-extract material survives the source file's removal. (Decision: Q3/r5.)
- One press of `e` commits the entire Working Set into a single Extract.
- **Extracts may span pages** — each Capture records its own page; the Working Set may include selections from several pages, and `e` commits them together. (Overrides the earlier single-page rule, Q1/r6.)
- `e` with an empty Working Set is a silent no-op (subtle status hint).
- **Yellow is never drawn over blue** — already-extracted content cannot be re-highlighted; attempting it is flagged in the UI.
- **Editing a text Capture affects only the persisted text shown in the Extracts View.** The source PDF is never modified; page and rectangle metadata are immutable once captured.
- **Deletion differs by surface**: in the reader, `d` twice deletes (key-driven); in the Extracts View, a confirmation popup deletes (mouse already in hand). Both are irreversible.
- **Content and existence are independent**: the Extract Editor may empty an Extract's text (one line or all of it) without any warning — content changes are the user's choice. Only the separate, confirmed delete act removes the Extract itself.
- **Edits in the Extracts View are undoable** (editor-session Ctrl+Z). Deletion stays irreversible; only typing is reversible.
- Reader keymap: `e` commit Working Set, `Esc` clear Working Set, `d` delete (twice), plus existing navigation/search keys.

## Storage
- Extracts live in `library.db` alongside `pdfs`, keyed by `doc_id`.
- `extracts` rows: `id`, `doc_id`, `created_at` (ordering), `type` ('text'|'image'|'combined', denormalized for cheap list UI).
- `captures` rows: `id`, `extract_id`, `page`, `rect` ('x0,y0,x1,y1' PDF-space), `kind`, `text_content` (kind='text', editable-replace), `image_blob` (kind='image', stored as PNG so extracts are PDF-independent).
- Image blobs are stored as PNG (lossless; study material is text-heavy).

## Status
- Created at start of grilling round 3. All terms settled through round 8.
- PR ① scope: capture flow (`e`/`Esc`/`d`-twice) + blue re-draw + Extracts View hierarchy + delete. No editing, no jump-back.
- PR ② scope: editing (text replacement, editor undo) + jump-back (routed through MainWindow).