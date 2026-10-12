# How to Use PDF Reader

A friendly, example-driven guide to everything the app can do today. Follow it top to bottom once and you'll have used every feature.

**Start the app** from the project folder:

```powershell
.\run.ps1
```

You'll see three buttons on the left: **📖 Library**, **📝 Extracts**, **🃏 Flashcards** (create, list and review).

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

**Back up your study data**: your Extracts, flashcards and study schedule all live in one file (`library.db`). Click **💾 Backup** in the Library header any time — it saves a consistent copy to the `backups/` folder next to the app, named with the date and time (e.g. `library-20261011-143000.db`), and tells you exactly where it went. Keep a copy somewhere safe (another drive, cloud folder). Old backups are trimmed automatically to the newest 10. **♻️ Restore** (next to Backup) loads one of those snapshots back: pick the snapshot, confirm, and your library is replaced in place — open Extracts or Flashcards to see the restored data. Restore asks before overwriting, so a misclick can't destroy anything.

### 2. Navigate like a pro (keyboard-first)

In the reader:

| Keys | Action |
|---|---|
| `j` / `k` (or `↓`/`↑`) | move down / up |
| `gg` / `G` | jump to top / bottom of the page |
| `Space` | page down |
| `/` | search — type, then `Enter` runs it and jumps to the first match (it lights up **green**, centred) |
| `Enter` / `n` / `N` | with a search active: next / next / previous match (wraps around) |
| `Esc` | close the search bar (or discard a pending selection) |
| `+` / `-` | zoom in / out |
| **Zoom: Fit** (click the label) | snap back to fit-width after zooming |
| Page box + `Enter` | jump to a page number (type `42`, press Enter — clamped to the document) |

Mouse works too — scroll and click as usual.

Search details: nothing runs while you type — press `Enter` to search, `Enter`/`n`/`N` to move between matches, `/` again to jump back into the search box. If no match is found the box stays focused so you can retype. After `Esc`, `n`/`N` go back to being next/previous page.

### 3. Capture something (the core loop)

**Capture a sentence:**

1. **Drag over some text** — it lights up **yellow** (this is a *Highlight*, still pending).
2. Press **`e`** — it turns **blue**: it's now an *Extract*, saved to disk.

**Capture several bits as one group:**

1. Drag over a sentence … then drag over another one on a different page. Yellow regions **stack** — they all sit in your *Working Set*.
2. Press **`e`** — everything you selected is committed **together as one Extract** (one group = one press of `e`).

**Capture an image:** just **click** it — the detected image goes yellow, then `e` works the same way.

**Changed your mind?** Press **`Esc`** — the yellow pending marks disappear without saving anything. (Going **◀ Back** or closing the app with pending marks asks first, so you don't lose them by accident.)

**Colors, one last time:**

- 🟡 **Yellow** = selected, not yet saved (Working Set)
- 🔵 **Blue** = saved Extract (survives restarts)
- 🟢 **Green** = the current search match
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

### 6. Turn a passage into a flashcard and review it

Flashcards quiz you on the passages you captured: a question on the front, your selected text and images on the back, resurfaced on a schedule (FSRS — the algorithm behind Anki).

**Make one (concrete example):**

1. Open any Extract in the **Extract Editor** (📝 Extracts → double-click a row — the one you captured in step 3 of this walkthrough is fine).
2. Drag over the sentence you want to be quizzed on — that selection becomes the **answer**. (In `test.pdf`, the "SuperMemo is easy if…" bullet on page 28 works well.)
3. Press **`Ctrl+K`** — or right-click the selection → **🃏 Make flashcard…** — or click **🃏 Make flashcard** in the editor toolbar. All three do the same thing: a dialog opens showing your selection as the answer preview, images inline.
4. Type the **question** — e.g. `What makes SuperMemo easy to start?` — and press **`Enter`** (or **Add Flashcard**). Done: the answer is copied at that moment, so editing the Extract later never changes the card. `Esc` in the dialog cancels without saving.

**Review it:**

5. Click **🃏 Flashcards** in the sidebar — your new card is at the top of the list, and **Next due** shows today's timestamp (fresh cards are due immediately).
6. Click **▶ Review (1)** — the session opens on your card, question first, progress "1 of 1".
7. Press **`Space`** — the answer appears (read-only, images included). Judge yourself, then grade: **`1` Again**, **`2` Hard**, **`3` Good**, **`4` Easy**.
8. Press **`3`** (Good, say) — the scheduler computes the next due time (a first-time Good keeps a new card due again **later today**, so it stays in today's set), the session ends with a one-line summary, and **Close** takes you back to the list. The **Next due** column shows the new time. Click **📅 Due today**: the card is still listed because it is still due today — a card graded into a later day disappears from that filter until its day comes round. Click the toggle again for All.

More entry points (right-click an image alone to card it), image-only cards, edit/delete, the **📅 Due today** filter and source jumps are covered under [Flashcards (make & list)](#flashcards-make--list) and [Review your cards (FSRS)](#review-your-cards-fsrs) below.

### 7. Close and come back later

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
| Reader | Navigate / search / zoom | `j` `k` `gg` `G` `Space` `/` `Enter` `n` `N` `Esc` `+` `-` |
| Extracts view | Read / edit an Extract | select row → `Enter` / double-click → type → **💾 Save** / **← Back** |
| Extracts view | Undo typing in the editor | `Ctrl+Z` |
| Extracts view | Open an Extract's origin in the reader | **↱ Jump** |
| Extracts view | Delete an Extract | select → 🗑️ Delete Selected (confirm) |
| Extract editor | Turn the selection into a flashcard | select → `Ctrl+K` (or right-click → 🃏 Make flashcard…, or toolbar 🃏 Make flashcard) → type question → `Enter` (or **Add Flashcard**) |
| Extract editor | Flashcard from an image alone | right-click the image (no text selection) → 🃏 Make flashcard from image… → type question → `Enter` |
| Flashcards | Browse your cards | sidebar **🃏 Flashcards** |
| Flashcards | See study stats | grey strip under the header: total cards, reviewed today, due tomorrow / next 7 days, and your 🔥 streak |
| Flashcards | Sort the list | click a column header (Question / Source / Created / Next due) |
| Flashcards | Find a card fast | type in 🔍 **Search cards…** (question + source name, case-insensitive) — ✕ or empty text clears |
| Flashcards | Edit a card's question | select the row → **✏️ Edit question** (or `F2`, or right-click → ✏️ Edit question…) |
| Flashcards | Delete a card | select the row → **🗑 Delete** (or `Del`, or right-click → 🗑 Delete) — asks first |
| Flashcards | Start a review session | **▶ Review (n)** — n = cards due today (new + due); disabled (with "No cards due today") when none |
| Flashcards | Show only today's due cards | **📅 Due today** (orange while on — exactly the Review session's set); click again for All |
| Flashcards | Open a card's source Extract | click the blue **Source** cell (live sources only — orphans show `⚠ source gone` and don't click) |
| Review session | Reveal the answer | `Space` (or **Show answer**) |
| Review session | Grade the card | `1` Again · `2` Hard · `3` Good · `4` Easy (or the buttons) |
| Review session | Close early | `Esc` (graded cards stay graded) |
| Review session | Finish the session | summary → **Close** (Again cards return first, total stays fixed) |
| Library | Add PDFs | ➕ Add PDF (or `Ctrl+O`, or **File → Add PDF…**) |
| Library | Open a PDF | double-click the row |
| Library | Tick rows to remove | row checkbox (or **☑ Select all** / **☐ Clear**) |
| Library | Remove the ticked PDFs | **🗑️ Remove Selected** (confirm) or `Delete` |
| Library | Back up your study data | **💾 Backup** — saves a copy of `library.db` to `backups/` and shows you where |
| Library | Load a previous backup | **♻️ Restore** — pick a snapshot from `backups/`, confirm, and the library is replaced |
| Library | Export flashcards for Anki | **📤 CSV** — pick a location, get `Question,Answer,Source,Due` rows (commas/newlines in answers are quoted correctly) |
| Library | Export your extracts as notes | **📤 MD** — one Markdown file: a heading per document, a sub-heading per extract, images marked `[image]` |
| Reader | Remember zoom per PDF | zoom in/out once — that PDF reopens at the same zoom; a first open starts at **Fit** |
| Anywhere | Jump between views | `Ctrl+1` Library · `Ctrl+2` Extracts · `Ctrl+3` Flashcards (or **View** menu) |
| Reader | Find / zoom / page from the menu | **Reader** menu: Find `Ctrl+F`, Zoom `Ctrl++`/`Ctrl+-`, Pages `PgUp`/`PgDown` — only while the reader is open |
| Anywhere | Keyboard shortcut list | `?` (in the reader) or **Help → Keyboard shortcuts…** (`Ctrl+/`) |

---

## Flashcards (make & list)

Turn any passage you selected into a flashcard:

1. Open an Extract in the **Extract Editor** (double-click its row).
2. Select the text that should become the **answer** — text, images, or both (a drag across text and images captures everything in between, in document order).
3. Open the dialog — any of: press `Ctrl+K`, right-click the selection → **🃏 Make flashcard…**, or click **🃏 Make flashcard** in the editor toolbar (all three work only while a selection exists). To flash a **single image without dragging**, just right-click it → **🃏 Make flashcard from image…**.
4. Type your **question** and press `Enter` (or **Add Flashcard**); `Esc` cancels — nothing is stored.

The answer is copied at that moment — text and image bytes alike — so editing the Extract afterwards never changes the card, and the card still shows its images even if the source document is removed. The dialog's answer preview displays the images inline, not just placeholder boxes. **🃏 Flashcards** in the sidebar lists every card — question, source document, created time, next due time — and a card whose source PDF was removed keeps that document's name (marked `⚠ removed source`, same as the Extracts tree) instead of hiding the source.

**Fix or remove a card from the list**: select its row and click **✏️ Edit question** (or press `F2`, or right-click the row) to correct a typo — only the question is written, so the card's schedule and next due date do not move; or click **🗑 Delete** (or press `Del`, or right-click) — a confirmation names the card, and confirming removes that card's question, answer, images and review history, **nothing else** (the source Extract stays in your library).

**Sort and search the list (#110)**: click any column header to sort (Question, Source, Created, Next due). Type in **🔍 Search cards…** in the header to narrow the list live — it matches the question **and** the source document name (case-insensitive), and combines with **📅 Due today** (search *within* today's due set). A search with no hits hides the table and says `No cards match “…”`; clearing the box brings every card back.

**Only see what's due today**: click **📅 Due today** in the header — the list then shows exactly the cards a Review session would grade (same rule: overdue, due later today, and brand-new cards; tomorrow's cards stay hidden, sorted soonest-first). Click it again to return to **All**. With nothing due, the table hides and the orange "No cards due today" hint explains why.

**Jump from a card to where it came from**: the **Source** column shows the document each card came from — in **blue** when it can be clicked. Clicking a blue source opens that Extract in the **Extract Editor** (the same view you get by double-clicking its row in the Extracts tree). Your study material is never lost when you clean up: if the source Extract was deleted, the card stays in the list, the source reads `⚠ source gone`, and it stops being clickable; if the whole PDF was removed from the library, the name stays with `⚠ removed source` (as before) and the jump is hidden too.

### Review your cards (FSRS)

The green **▶ Review (n)** button shows how many cards are due **today** (brand-new cards are due immediately; graded cards resurface when the scheduler says so). Clicking it starts a session:

1. A **shuffled queue** of those cards, one at a time — question first, with **"n of m"** progress (`m` = the number of cards due today, fixed for the whole session).
2. Press **`Space`** (or **Show answer**) to reveal the answer — read-only, images included.
3. Grade it: **`1` Again**, **`2` Hard**, **`3` Good**, **`4` Easy** (or click the buttons). The FSRS scheduler computes the next due date, saves it, and the next card appears.
4. **Again cards come back in the same session**: they are re-queued at the end (once each), so the queue's total stays fixed — "2 of 5" never becomes "6 of 5" — and the card is shown again before the session ends (the counter keeps reading `2 of 5` but is marked `· again`, so you can tell a repeat from a first showing). It is still due for the rest of today afterwards, and grading it again builds on the first grade rather than starting over.
5. When the last card is graded you get an **end-of-session summary** ("Session complete — 5 cards reviewed (2 Again)") with a **Close** button back to the list; the **Next due** column already shows the new dates. **`Esc`** closes early — anything you already graded stays graded.

Nothing is due? The Review button is **disabled (0)** and an orange **"No cards due today"** hint sits under it — no empty session opens. Come back tomorrow (or make new cards).

---

## Reporting slowness (perf log)

If anything ever feels slow (opening a PDF, Back, scrolling), turn on the timing log:

1. Create an empty file called `perf.enabled` in `pdf_reader\gui_app\` (or set `$env:PDFR_DEBUG_PERF="1"` before launching).
2. Start the app with `run.ps1` — it prints `[perf] logging ON → console + …\perf.log`.
3. Do the slow thing, then close the app.
4. Send the file `pdf_reader\gui_app\perf.log`. Each line is one timing, for example:
   `back: click -> library first paint: 8.45 ms` — that is the full Back journey: click, database update, view switch, and the first frame you actually see.

Delete `perf.enabled` to switch logging off again.

---

## Not available yet (honest list)

No feature is currently queued — everything designed is in the app today. The one tracked follow-up is **standalone packaging** (an installer so you can run the app without a Python environment).

Update this section whenever a feature ships — this guide is a live document (see `AGENTS.md`).
