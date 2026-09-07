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

**Never pad a short bar with rests.** Padding makes every bar sum to its meter,
so `verify_score.py` reports "0 problems" while notes and dots are missing —
book 6 song 1 was delivered that way, verifying clean with four dropped dots
and two absent notes. A short bar is a visible defect; a padded one is an
invisible one. `split_shared_staff.py` leaves holes open and reports them;
`--pad-holes` exists but is for a score already reconciled. Note that music21
re-pads incomplete measures when it WRITES, so completeness must be judged from
notes, never from a written file.

**Exhaust the repeats before reaching for the scan.** These books are strophic:
the same phrase is stated three or four times and the OMR damages each copy
differently, so the correct reading of a damaged bar is usually already in the
file. `reconcile_repeats.py` recovered four of the eight bars a musician had to
fix by hand in book 6 song 1, at no cost, and declined the other four instead
of guessing.

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

# 3. Run Audiveris per song range (sheet2xml, or -sheets N-M on an .omr).
#    Keep the .omr and raw exports NEXT TO THE BOOK, not in a session
#    scratchpad -- it is ~10 min of CPU and scratch gets wiped.

# 3b. If the melody SHARES a staff with the accompaniment (see "Shared staff")
scripts/split_shared_staff.py raw/song_01.mxl --out-base out/song_01

# 3c. Reconcile repeated bars BEFORE looking at the scan -- cheapest repair
scripts/reconcile_repeats.py out/song_01_melody_raw.musicxml --apply \
    -o out/song_01_melody.musicxml

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

Check any advisory's precision before investigating a single flag. If its
false positives outnumber its true ones — clef blobs, open noteheads, text
above the staff, accidental spellings — suppress those classes first. Chasing
a noisy checker costs more than fixing it.

## Shared staff: when there is no melody staff to crop

Check the engraving before assuming a separate melody staff. SMOM books 1-5
print melody + piano grand staff (3 staves per system); **book 6 prints the
vocal line INSIDE the piano treble staff** (2 staves per system, verses set
between them). There the crop route below does not exist, `melody_staves.py
--per-system 3` finds nothing usable, and Audiveris' voice numbering does not
track the melody — in book 6 song 1 voice 1 filled only 9 of 17 bars.

Use `split_shared_staff.py`: the melody is the top line, recovered as a skyline
(highest pitch at each onset). Two failures are systematic and expected —
dropped dots on the dotted-eighth+sixteenth figure, and melody notes that share
a notehead with the right hand, where the OMR merges them into one chord and the
melody inherits the ACCOMPANIMENT's duration. Run `reconcile_repeats.py` next;
it fixes both wherever the bar repeats one that read cleanly.

Also read the page geometry before trusting either staff finder: both
`find_title_bands.py` and `melody_staves.py` have their gap and minimum-height
constants tuned for portrait pages. Book 6's landscape scans (768x500pt) render
too small at the default `--scale`, so every staff fails the five-line test.
Raise `--scale` and check the reported staff count against a page you have
looked at. If the book has a printed contents page, reading it is far cheaper
than reading title bands.

**For a melody-only job on a 3-staff book, crop the melody staff out and run
Audiveris on that**
— `scripts/melody_staves.py book.pdf --pages 15-17 -o mel.pdf`, one system per
page (leave `--dpi` alone; Audiveris refuses images over 20M pixels). The
accompaniment is what scrambles part assignment: a grand staff below the vocal
line makes Audiveris hand measures to the wrong part, silently drop a page, or
die outright (`Denominator is zero` at every resolution, clean once the piano
was gone). Settle the route on ONE song run both ways before committing a whole
book to either, then keep the loser as a second pass: two readings of the same
staves disagree only where one is wrong, so every difference is a bar to open
the scan on. Diff them by note sequence, not bar number — one disagreement
about a pickup shifts every later bar.

## What needs your eyes

**Read the key signature off the page yourself, once per song, before anything
else.** Never inherit it from the OMR output. It is a single glance at the front
of the first system, and getting it wrong is silent: `read_staff` is *given* the
key, so it cannot disagree, and a comparison in staff steps cannot either, since
Bb and B natural sit on the same line. One wrong signature quietly rewrites every
affected note in the piece and everything built on it.

**Never read pitch off a small crop.** Comparing noteheads to each other by eye
turns a third into a second. Measure them against the staff lines:

```bash
scripts/read_staff.py book.pdf --page 10 --region 0.7,0.11,0.9,0.21 --key -1
```

**A staff engraved in dyads needs `read_dyads.py` instead.** Two noteheads a
third apart touch, and the merged blob fails `read_staff`'s height test — so
most of a duet silently fails to appear, as absent notes rather than an error.
`read_dyads.py` splits those blobs and prints each stack highest-first, which is
also how you recover the two parts: upper voice, lower voice.

It prints each notehead's diatonic step and warns when a staff space is under
~60px (re-render larger) or a reading lands between two pitches. Rhythm is
readable far smaller than pitch is, so a bar whose rhythm you have confirmed is
**not** thereby pitch-confirmed — check the two separately, per bar.

**Match the instrument to the question.** They run cheapest to dearest: bar
arithmetic, then a diff of two independent runs, then measurement, then a
rendered image. An image is the wrong tool for a pitch — measure it instead;
the detector is the wrong tool for a dot, a flag or a rest — look at those.
Never render blind: derive the crop window from a measurement first, or you
will render the same bar three times before it is legible.

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
  with `--anacrusis always`. Overriding does NOT fix the final bar: it unpads
  the pickup and leaves the arithmetic unbalanced. If the source engraves an
  upbeat, the final bar has to be shortened to complete it (pickup 0.5 + final
  1.5 = one 2/4 bar), which is what a musician corrected by hand on book 6
  song 1.

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
