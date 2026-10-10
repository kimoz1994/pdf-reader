# How to Use PDF Reader

A friendly, example-driven guide to everything the app can do today. Follow it top to bottom once and you'll have used every feature.

**Start the app** from the project folder:

```powershell
.\run.ps1
```

You'll see three buttons on the left: **📖 Library**, **📝 Extracts**, **🃏 Flashcards** (create + list — the review session comes later).

---

## The idea in one paragraph

While you read, interesting bits are marked **yellow** (pending). Press `e` and they become **blue** — permanent *Extracts* stored in your library, grouped exactly as you selected them. You can review, read, and jump back to them any time, even after restarting the app.

---

## Walkthrough: a study session

We'll use the bundled sample `test.pdf` so you don't need your own file (or add one — step 1).

### 1. Add a PDF to your library

1. Click **📖 Library**.
2. Click **➕ Add PDF** and pick a file (or `pdf_reader/pdfs/test.pdf`).
3. It appears in the list with its read progress. **Double-click** it to open the reader.

> Your place is remembered: reopen the same PDF later and you land on the last page you read.

**Remove PDFs from the library** (only from the library — the files on disk are never deleted, and your Extracts and flashcards stay):

1. Tick the **checkbox** on each row you want to remove — or click **☑ Select all** to tick every row at once (it flips to **☐ Clear**).
2. **🗑️ Remove Selected** shows how many are ticked (e.g. `🗑️ Remove Selected (3)`) and only lights up when at least one is; the stats line under the list shows `— N selected`.
3. Click it (or press **`Delete`** with the list focused) and confirm: the dialog lists the ticked names behind **Show details** and reminds you the files themselves are untouched.
4. A file you moved or deleted elsewhere no longer vanishes from the list — it stays marked **⚠ file missing** in orange, so you can tick and remove it like any other row (double-clicking it explains it can't be opened).

### 2. Navigate like a pro (keyboard-first)

In the reader:

| Keys | Action |
|---|---|
| `j` / `k` (or `↓`/`↑`) | move down / up |
| `gg` / `G` | jump to top / bottom of the page |
| `Space` | page down |
| `/` | search on the page |
| `+` / `-` | zoom in / out |

Mouse works too — scroll and click as usual.

### 3. Capture something (the core loop)

**Capture a sentence:**

1. **Drag over some text** — it lights up **yellow** (this is a *Highlight*, still pending).
2. Press **`e`** — it turns **blue**: it's now an *Extract*, saved to disk.

**Capture several bits as one group:**

1. Drag over a sentence … then drag over another one on a different page. Yellow regions **stack** — they all sit in your *Working Set*.
2. Press **`e`** — everything you selected is committed **together as one Extract** (one group = one press of `e`).

**Capture an image:** just **click** it — the detected image goes yellow, then `e` works the same way.

**Changed your mind?** Press **`Esc`** — the yellow pending marks disappear without saving anything.

**Colors, one last time:**

- 🟡 **Yellow** = selected, not yet saved (Working Set)
- 🔵 **Blue** = saved Extract (survives restarts)
- 🟠 **Orange flash** = “you are here” marker when you jump to a region (below)

### 4. Review your extracts

1. Click **📝 Extracts** in the sidebar.
2. You'll see a tree: **Document → Extract**, newest first — one row per Extract. Expand with `+`.
   - Document rows show the PDF's own **title** (read from its metadata), falling back to a tidied filename (`2020-11-11_v5.0_Supermemo_lore.pdf` → `2020-11-11 v5.0 Supermemo lore`).
   - If you removed the PDF from the library, its Document row **stays** and keeps showing the original title (each Extract snapshots its Document's title, so removing the PDF doesn't lose the name) with a ⚠ removed source marker; if the file was deleted from disk the row is marked ⚠ file missing instead — the Extracts inside remain readable, editable and deletable either way, and ↱ Jump shows a warning instead of jumping. (Documents removed before this fix keep `⚠ Removed source (doc #N)` — their names were already gone.)
   - `Extract #2 — text (3 captures)` means “3 pieces captured together”.
   - Each Extract row **previews its content**: the opening of its first text (e.g. `…: The mitochondria is the powerhou…`), the page span for image-only extracts (`…: pp. 4–5`), `(pasted)` for an Extract made only of pasted images, or `(empty)` — so you know what's inside before opening it.
3. **Read and edit an Extract full-page**: select its row and press **Enter** (or double-click). The whole view becomes the **Extract Editor**: the group's text and images as **ONE continuous document** — a single editable surface where the cursor flows across capture boundaries, with images sitting inline between text (type before, after and around them; deleting an image's placeholder removes that image from the document on save — its Capture stays as the blue anchor, so blue redraw and ↱ Jump are unaffected; the label's page span always covers the images still in the document). `Ctrl+Z` undoes across the whole Extract. Click **💾 Save** to persist without leaving, or just press **← Back**: it auto-saves and returns you to the tree with the same row still selected, the preview showing your edited text (or `(empty)` if you emptied it). You can even empty the whole document — the Extract stays in the tree. To resize an inline image, **right-click it** (Bigger `+` / Smaller `-` / Reset to auto size) or put the cursor on it and press **`+`/`-`**: the new size is stored with that image and survives restarts; **Reset** puts it back on the automatic size band. You can also **paste an image straight into the editor** - copy an image (e.g. a screenshot) and press **Ctrl+V**: it drops in at the cursor and is saved with the Extract like any other image (a pasted image has no source page, so ↱ Jump still anchors on the Extract's first real page).
4. **Delete an Extract**: select it and click **🗑️ Delete Selected** (you'll be asked to confirm; the whole Extract goes). A Document row (or no selection) pops a hint instead. In the reader, the shortcut is **`d` twice**.

### 5. Jump back to where it came from

Ever forget where a highlight came from? In the Extracts view, click **↱ Jump** on an Extract row:

- the reader opens the right document,
- scrolls so the original region is **centered**, and
- an **orange outline flashes** on it for a second so your eye catches it.

Your read progress is untouched. The reader's **◀ Back** button then takes you to whichever view you came from — the **Extracts list** after a jump, the **Library** when you opened the PDF from there.

### 6. Close and come back later

Everything — your library, your read position, your blue extracts — lives in a small local database (`library.db`). Just start the app again and carry on.

---

## Cheat sheet

| Where | Action | How |
|---|---|---|
| Reader | Select text | drag |
| Reader | Select an image | click |
| Reader | Save pending selection(s) as an Extract | `e` |
| Reader | Discard pending selection(s) | `Esc` |
| Reader | Delete newest Extract on this page | `d` `d` |
| Reader | Navigate / search / zoom | `j` `k` `gg` `G` `Space` `/` `+` `-` |
| Extracts view | Read / edit an Extract | select row → `Enter` / double-click → type → **💾 Save** / **← Back** |
| Extracts view | Undo typing in the editor | `Ctrl+Z` |
| Extracts view | Open an Extract's origin in the reader | **↱ Jump** |
| Extracts view | Delete an Extract | select → 🗑️ Delete Selected (confirm) |
| Extract editor | Turn the selection into a flashcard | select → `Ctrl+K` (or right-click → 🃏 Make flashcard…, or toolbar 🃏 Make flashcard) → type question → `Enter` (or **Add Flashcard**) |
| Extract editor | Flashcard from an image alone | right-click the image (no text selection) → 🃏 Make flashcard from image… → type question → `Enter` |
| Flashcards | Browse your cards | sidebar **🃏 Flashcards** |
| Library | Add PDFs | ➕ Add PDF |
| Library | Open a PDF | double-click the row |
| Library | Tick rows to remove | row checkbox (or **☑ Select all** / **☐ Clear**) |
| Library | Remove the ticked PDFs | **🗑️ Remove Selected** (confirm) or `Delete` |

---

## Flashcards (make & list)

Turn any passage you selected into a flashcard:

1. Open an Extract in the **Extract Editor** (double-click its row).
2. Select the text that should become the **answer** — text, images, or both (a drag across text and images captures everything in between, in document order).
3. Open the dialog — any of: press `Ctrl+K`, right-click the selection → **🃏 Make flashcard…**, or click **🃏 Make flashcard** in the editor toolbar (all three work only while a selection exists). To flash a **single image without dragging**, just right-click it → **🃏 Make flashcard from image…**.
4. Type your **question** and press `Enter` (or **Add Flashcard**); `Esc` cancels — nothing is stored.

The answer is copied at that moment — text and image bytes alike — so editing the Extract afterwards never changes the card, and the card still shows its images even if the source document is removed. The dialog's answer preview displays the images inline, not just placeholder boxes. **🃏 Flashcards** in the sidebar lists every card — question, source document, created time, next due time — and a card whose source PDF was removed keeps that document's name (marked `⚠ removed source`, same as the Extracts tree) instead of hiding the source.

---

## Not available yet (honest list)

These are designed and queued — don't look for them in the app today:

- **Flashcard review session** (grading Again/Hard/Good/Easy, FSRS scheduling, due-today filtering) — cards can be created and listed today; reviewing them is queued.

Update this section whenever a feature ships — this guide is a live document (see `AGENTS.md`).
