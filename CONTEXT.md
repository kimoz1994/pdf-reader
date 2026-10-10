# CONTEXT.md

Domain vocabulary for the PDF reader. This is a glossary, not a spec.

## Concepts

### Document
A PDF file added to the library. Persisted in `library.db`. Has a path, a name, a page count, and a last-opened page (read progress). A document contains **Extracts**. Removal is **library-only**: ticking one or more rows and confirming deletes their `pdfs` rows — never the files on disk — and the Extracts/flashcards survive under the original title (#70). A Document whose file is missing stays listed, marked `⚠ file missing`, so it can be removed too (#72).

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
An individual snippet inside an Extract (one text region or one image region). An Extract is composed of one or more Captures taken together. Image regions rasterize at 2× PDF scale (sharp captures; the anchor geometry stays in PDF points). A Capture created by **pasting** an image in the Extract Editor has **no page/rect** - no PDF anchor: it never blue-redraws in the reader and is skipped by the reader's highlight math.

### Extracts View
The screen where the user reviews extracted material. Shows a hierarchical list: the library's **Documents**, each expandable (`+`) into its **Extracts** (each row previewing a snippet of its content). Opening an Extract replaces the list with the **Extract Editor**; closing it returns to the list. A Document whose source PDF was removed from the library **stays listed under its original title** — every Extract snapshots its Document's display title (`extracts.doc_name`, #70), so removal keeps the name and only marks the row `⚠ removed source` (a Document removed before the snapshot existed keeps `⚠ Removed source (doc #N)`); a PDF deleted from disk instead shows `⚠ file missing`. Its Extracts remain readable, editable and deletable (Extracts are independent of the PDF, Q3/r5; Jump warns instead of jumping).

### Extract Editor
The full-area editing surface for one Extract: **ONE continuous document** — the whole Extract as a single editable text surface (one cursor, one undo history) with image Captures rendered **inline** at their placeholder positions, in capture order. Text can be typed before, after and between images; images can be typed around and deleted — deleting an image's placeholder removes it from the document on save (the Capture row stays as the immutable page anchor, so blue redraw + Jump are unaffected); pasted placeholder duplicates are stripped. Images resize in place (right-click menu Bigger/Smaller/Reset or +/- with the cursor on the image) — the width persists in `captures.display_w` (NULL = auto size band); presentation only, the `page`/`rect` geometry anchors never change. The clipboard's image can be **pasted in** (Ctrl+V): it renders inline at once and becomes a page/rect-NULL Capture on save; an Extract that is only pasted images previews `(pasted)` and hides ↱ Jump (Jump anchors on the first capture that has a page).
**Status**: joined editing (ticket #32 — shipped): the Extract's text is one blob (`extracts.text_content`) typed into as a single document, word-wrapped, `Ctrl+Z` spanning the whole Extract. **Save** persists mid-session; **Back** auto-saves. Emptying the whole text is allowed and never removes the Extract.
_Avoid_: per-capture editor boxes (retired), inline editor (retired), rich text (formatting is out of scope for now).

### Flashcard
A question paired with an **answer snapshot** — a copy of what was selected in the Extract Editor, taken at creation. The snapshot is text with images marked U+FFFC plus the image PNG bytes stored per card in `flashcard_images` (card-owned copies, not references — the card survives source removal and still renders its images, #56). Mixed selections (text + images) snapshot both in document order. The snapshot is **immutable**: later edits to the source Extract never change the card. Created from the Extract Editor through the selection entry points — right-click **🃏 Make flashcard…**, the toolbar **🃏 Make flashcard** button, or `Ctrl+K` — or by right-clicking an image with no text selection (**🃏 Make flashcard from image…**, the image alone as the answer). The dialog previews images inline; `Enter` submits (`Esc` cancels). Listed in the **Flashcards View** (question, source document, created, next due). Scheduling fields exist from day one (`due_utc` ISO-8601 UTC — a fresh card is due immediately; `fsrs_json` NULL until the FSRS scheduler lands, #58). Cards survive their source: an orphaned card keeps its source name and marks it `⚠ removed source` — the same marker the Extracts tree uses — from the Extract's `doc_name` snapshot (#70), and shows no source only when no snapshot exists.
_Avoid_: deck (no decks yet), note (that's an Extract).

### Un-extract
The act of deleting an Extract from the reader (`d`) or deleting it in the Extracts View. **Irreversible** — there is no undo and no soft delete in either view. Both paths show a confirmation prompt before the delete happens.

### Clear (Working Set)
Dismissing all pending Highlights (`Esc`) without committing anything. The Working Set is also cleared whenever the reader changes document or the document is closed — per-session, never global.

## Rules
- Delete is whole-Extract only; a Capture cannot be removed on its own.
- Image Captures are immutable (cannot be edited, only deleted as part of the Extract).
- Extracts are always drawn in the reader as transparent blue regions when the document is open (equivalent to how yellow highlight is shown in common PDF readers).
- Extracts are listed newest-first in the Extracts View.
- **Extracts aim to be independent of the PDF** — image data is stored in the DB (blob), not referenced, so left-extract material survives the source file's removal. (Decision: Q3/r5.)
- One press of `e` commits the entire Working Set into a single Extract.
- **Extracts may span pages** — each Capture records its own page; the Working Set may include selections from several pages, and `e` commits them together. (Overrides the earlier single-page rule, Q1/r6.)
- `e` with an empty Working Set is a silent no-op (subtle status hint).
- **Yellow is never drawn over blue** — already-extracted content cannot be re-highlighted; attempting it is flagged in the UI.
- **Editing the Extract's text replaces the stored blob** — the Extract becomes the user's version; the exact original quote is not kept alongside.
- **Editing the Extract's text never touches geometry** — the source PDF is never modified; page and rectangle metadata are immutable once captured.
- **Deletion differs by surface**: in the reader, `d` twice deletes (key-driven); in the Extracts View, a confirmation popup deletes (mouse already in hand). Both are irreversible.
- **Content and existence are independent**: the Extract Editor may empty an Extract's text (one line or all of it) without any warning — content changes are the user's choice. Only the separate, confirmed delete act removes the Extract itself.
- **Edits in the Extracts View are undoable** (editor-session Ctrl+Z). Deletion stays irreversible; only typing is reversible.
- Reader keymap: `e` commit Working Set, `Esc` clear Working Set, `d` delete (twice), plus existing navigation/search keys.

## Storage
- Extracts live in `library.db` alongside `pdfs`, keyed by `doc_id`.
- `extracts` rows: `id`, `doc_id`, `created_at` (ordering), `type` ('text'|'image'|'combined', denormalized for cheap list UI), `text_content` (the whole-Extract text blob; inline images marked U+FFFC, one per image Capture in capture order).
- `captures` rows: `id`, `extract_id`, `page`, `rect` ('x0,y0,x1,y1' PDF-space), `kind`, `text_content` (always NULL — captures are anchors, never text), `image_blob` (kind='image', stored as PNG so extracts are PDF-independent).
- Pre-blob databases migrate once on `init_schema`: per-capture text is folded into the blob (capture-id order, images as placeholders) and capture text is NULLed. Idempotent via a column-existence check.
- Image blobs are stored as PNG (lossless; study material is text-heavy).
- Flashcards live in `library.db` too: `flashcards(id, extract_id, doc_id — all nullable so cards survive source removal, question, answer_text, created_at, fsrs_json, due_utc)`; image blobs per card in `flashcard_images` (written at creation, #56), ratings in `review_logs` (schema-ready, written from #58).

## Status
- Created at start of grilling round 3. All terms settled through round 8.
- PR ① scope: capture flow (`e`/`Esc`/`d`-twice) + blue re-draw + Extracts View hierarchy + delete. No editing, no jump-back.
- PR ② scope: editing (text replacement, editor undo) + jump-back (routed through MainWindow).
- Superseded by spec #22, which shipped as issues #23 (previews), #24 (editor read), #25 (editor editing); reader back-nav landed separately (#28). Old PR-②-era issues (#10, #13, #14, #15, #19, #21) are closed as superseded.
- Flashcards floor shipped as spec #54 / issues #55/#56/#57 (schema, store, selection-snapshot seam, editor dialog with inline image preview, image-alone right-click, card list); review session, row actions and the docs pass are tracked as #58–#63.