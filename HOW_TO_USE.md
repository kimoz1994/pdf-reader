# How to Use PDF Reader

A friendly, example-driven guide to everything the app can do today. Follow it top to bottom once and you'll have used every feature.

**Start the app** from the project folder:

```powershell
.\run.ps1
```

You'll see three buttons on the left: **📖 Library**, **📝 Extracts**, **🃏 Flashcards** (placeholder — not ready yet).

---

## The idea in one paragraph

While you read, interesting bits are marked **yellow** (pending). Press `e` and they become **blue** — permanent *Extracts* stored in your library, grouped exactly as you selected them. You can review, fix, and jump back to them any time, even after restarting the app.

---

## Walkthrough: a study session

We'll use the bundled sample `test.pdf` so you don't need your own file (or add one — step 1).

### 1. Add a PDF to your library

1. Click **📖 Library**.
2. Click **➕ Add PDF** and pick a file (or `pdf_reader/pdfs/test.pdf`).
3. It appears in the list with its read progress. Click it to open the reader.

> Your place is remembered: reopen the same PDF later and you land on the last page you read.

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
2. You'll see a tree: **Document → Extract → Captures**, newest first. Expand with `+`.
   - Document rows show the PDF's own **title** (read from its metadata), falling back to a tidied filename (`2020-11-11_v5.0_Supermemo_lore.pdf` → `2020-11-11 v5.0 Supermemo lore`).
   - `Extract #2 — text (3 captures)` means “3 pieces captured together”.
   - Each Extract row **previews its content**: the opening of its first text (e.g. `…: The mitochondria is the powerhou…`), the page span for image-only extracts (`…: pp. 4–5`), or `(empty)` — so you know what's inside before opening it.
3. **Fix a typo** in a saved text capture: **double-click the text capture row** (or select it and press `Enter`). An inline editor opens — type your correction, then:
   - **`Enter`** or clicking away → saves
   - **`Esc`** → cancels, old text stays
   - (Blank text is rejected — an empty capture is never saved.)
4. **Delete an Extract**: select it and click **🗑️ Delete Selected** (you'll be asked to confirm). In the reader, the shortcut is **`d` twice**.

### 5. Jump back to where it came from

Ever forget where a highlight came from? In the Extracts view, click **↱ Jump** on an Extract row (or press `Enter` on it):

- the reader opens the right document,
- scrolls so the original region is **centered**, and
- an **orange outline flashes** on it for a second so your eye catches it.

Your read progress is untouched.

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
| Extracts view | Open an Extract's origin in the reader | **↱ Jump** (or `Enter` on the row) |
| Extracts view | Edit a text capture | double-click the row → edit → `Enter` |
| Extracts view | Cancel an edit | `Esc` |
| Extracts view | Delete an Extract | select → 🗑️ Delete Selected (confirm) |
| Library | Add / remove PDFs | ➕ Add PDF / 🗑️ Remove Selected |

---

## Not available yet (honest list)

These are designed and queued — don't look for them in the app today:

- **Full-area Extract Editor** — the whole view becomes a Word-like editor showing a whole group's text *and* images together (spec #22, tickets #24–#25)
- **Round-trip back** from a jumped-to region to the Extract list (#13)
- **Per-capture jump rows** (#14)
- **Flashcards** (sidebar button says “coming soon”)
- **Extracts when the source PDF is removed** — they're safe in the database, but hidden from the list until #17 is fixed

Update this section whenever a feature ships — this guide is a live document (see `AGENTS.md`).
