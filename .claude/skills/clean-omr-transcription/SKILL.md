---
name: clean-omr-transcription
description: Post-OMR cleanup pipeline for scanned sheet music - turns raw Audiveris MusicXML into a trustworthy melody-only or melody+accompaniment MusicXML/MuseScore score. Covers song-boundary splitting, scan-resolution tuning, non-destructive measure-length repair, anacrusis and tuplet correctness, melody selection, and voice/hidden-element cleanup. Complements sheet2xml, which only runs the OMR engine.
allowed-tools: Read Bash Grep Glob Write Edit
argument-hint: [raw-omr-musicxml-or-source-pdf]
effort: medium
---

# Clean OMR Transcription

Turn raw Audiveris + music21 output into a score a musician can trust.

**Governing principle: melody-note accuracy wins.** The scripts never delete a
note — they repair or report. When one reports a problem it cannot fix, decide;
don't reach for a fix that trades notes for tidiness.

**Never invent rhythm.** Dotted notes and tuplets must not appear where the
source has none. Both are created the same way — by a repair reaching for a
longer note value to make a bar add up — and neither is caught by any check of
measure length, note count or voices; a bar full of invented dotted quarters
passes all three. `normalize_measures.py` therefore counts dotted and tuplet
elements before and after every run and reports any increase as `INVENTED`.
Treat that as a defect, not a note: the rules and the reasoning are in
`references/rare-repairs.md`, and the specific traps are listed there.

The rules live in `scripts/`, not in this file. Run them; read them only if one
misbehaves. All paths below are relative to this skill's directory.

## Pipeline

```bash
# 1. Before blaming OMR quality, check the scan geometry
scripts/fix_pdf_geometry.py book.pdf --report
scripts/fix_pdf_geometry.py book.pdf -o book_fixed.pdf   # if it says REBUILD

# 2. Find where each song starts (see "What needs your eyes")
scripts/find_title_bands.py book.pdf --out /tmp/bands --first-page 4

# 3. Run Audiveris per song range (sheet2xml, or -sheets N-M on an .omr)

# 4. Clean each raw export
scripts/normalize_measures.py raw/*.mxl --out-dir out --melody-only \
    --composer "..."

# 5. Verify what was actually delivered — including the .mscz if you ship one
scripts/verify_score.py out/*.musicxml --max-voices 1
scripts/verify_score.py out/*.mscz --max-voices 1
```

`normalize_measures.py` verifies its own output, so step 5 matters most for
files that went through another tool (a `.mscz` round trip, a manual edit).
Both scripts exit non-zero on any problem, so they gate a loop.

`verify_score.py` also prints **rhythm suspects** — bars where a dot was
probably dropped. It names the bars; you settle them against the scan.

## What needs your eyes

Five things no script can settle:

1. **Reading the titles.** `find_title_bands.py` crops and stacks the bands;
   you read the composites. A scanned PDF has no text layer and the `.omr`
   usually has no OCR either. Confirm each song runs from its numbered title to
   just before the next number up.
2. **Whether a page-range split is safe.** The script reports mid-page bands.
   Any of them that is a *title* (not lyrics) means a song starts mid-page and
   page ranges will cut songs in half. Also watch for an unnumbered appendix at
   the end, and exclude the staff-less pages it lists (extra verses set as text).
3. **Comparing a render against the scanned source.** The only check that
   catches a wrong pitch; structural checks never will. Sample the songs with
   multiple "Voice" parts, irregular measures, or low OMR confidence.
4. **Any `INVENTED` report.** The count is automatic; deciding whether a
   genuine increase is justified is not. The only legitimate one seen so far is
   a degenerate bar whose ornaments were unreadable until it was rescaled.
5. **Note-count deltas.** Compare raw vs final per part. Expect legitimate
   movement — tie splitting inflates counts, collapsing duplicate-verse voices
   or unison doublings reduces them. Localize before treating a delta as loss.

## Defaults that are judgment calls

| Flag | Default | When the default is wrong |
|---|---|---|
| `--melody-only` | off | Usually **on** is right: it's cheaper and skips the voice-flattening that endangers tuplets. Ask before transcribing the piano. |
| `--anacrusis` | `auto` | `auto` unpads a rest-padded pickup only when pickup + final bar completes one bar. Shape alone can't tell a padded pickup from an opening bar the composer wrote full. Use `always` if house style is that every upbeat is engraved as a short pickup bar. |
| `--no-triplets` | off | Tuplets are kept only where **obvious** — the engine tagged the run AND the bar already sums to its meter with it. An engine tag alone is not evidence: Audiveris emits tuplets as a by-product of misreading a bar. Use this flag to suppress them entirely. |
| `--min-trailing-rests` | 2 | Trailing all-rest bars are deleted once this many follow the last note. |
| `--max-voices` | 2 | Use 1 for melody-only. |

## When a script reports a problem

- **`OVERLONG`** — a bar the ordered repairs could not fit. See
  `references/rare-repairs.md`. Never resolve it by deleting a note.
- **`short`** — a bar under its meter outside the legal pickup/final positions.
  Usually a missed meter, not a missed note.
- **`rhythm suspect`** — advisory, never gates. A dropped dot is the one rhythm
  error that passes every structural check: the bar still fills its meter, so
  nothing else can see it. Two signals catch it. *Residue*: a bar ending in a
  rest shorter than a beat is the gap the missing dot left. *Outlier*: a bar
  that would match a rhythm the song uses elsewhere if one dot were restored —
  this is the only signal when a dotted-eighth-plus-sixteenth was read as two
  eighths, which fills the beat exactly and leaves no gap. Both are guesses
  about where to look, so open the scan for those bars; neither can confirm
  anything on its own. `--rhythm-support N` sets how many other bars must carry
  the repaired pattern (default 3; lower flags ordinary bars of four eighths).
- **`rest in non-primary voice` / `print-object="no"`** — the file will
  reintroduce hidden rests on the next round trip. Re-run with one voice per
  staff; see `references/multi-part.md` for why voice numbering misleads here.
- **`WRITE DID NOT CONVERGE`** — music21's exporter inflated a part's measure
  count (observed 301 → 418) with no error. `safe_write` already retried from
  the in-memory score five times. Do not "fix" it by re-parsing and rewriting
  the written file; that compounds it. Confirm a manual MuseScore fix with the
  user rather than shipping corruption.
- **`INVENTED n dotted` / `INVENTED n tuplets`** — a repair added ornaments the
  source does not have. Do not ship it. Find which repair widened the vocabulary
  (`references/rare-repairs.md` names the three that can).
- **`anacrusis-rejected-by-arithmetic`** — a bar looked like a padded pickup
  but pickup + final didn't complete a bar. Check the source before overriding
  with `--anacrusis always`.

## Naming

`{BOOK_ABBR}_{book_number}_{song_number:02d}_{slug}_v{version}.musicxml`
(e.g. `SMOM_1_01_julafton_v1.musicxml`) — `omrlib.deliverable_name()` builds it.

- `BOOK_ABBR`: initials of the book title, fixed once per series.
- `song_number`: order of appearance **in the book**, not OMR sheet numbering.
- `version`: bump when replacing an already-delivered set with a materially
  different transcription; overwrite in place only while still iterating before
  hand-off. Restart at `v1` only if the convention itself changes.

**Rename per-song files only.** Leave combined whole-book deliverables under
their existing names (confirm rather than assuming). On a re-run, output names
derive from the *raw source* filename, so delete stale renamed files first
instead of expecting overwrites.

## Process notes

- Re-exporting via `-sheets N-M` produces either `<bookname>.mxl` or
  `<bookname>.mvtnull.mxl` — check both, or every song silently overwrites the
  same scratch file. Audiveris ignores `-output` for `.omr` input and writes
  beside the book.
- Don't run Audiveris books in parallel; CPU-heavy steps (SYMBOLS/BEAMS)
  throttle each other even with idle cores.
- Never raise Audiveris's `maxPixelCount` to allow native resolution — large
  images hit a hardcoded step timeout regardless of the pixel cap.

## Conditional references

- `references/multi-part.md` — grand staff and combined-book assembly. Load
  only when accompaniment or a whole-book score is in scope.
- `references/rare-repairs.md` — bars that resist the ordered repairs.
