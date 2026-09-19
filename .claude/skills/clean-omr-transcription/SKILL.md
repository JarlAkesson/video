---
name: clean-omr-transcription
description: Post-OMR cleanup pipeline for scanned sheet music - turns raw Audiveris MusicXML into a trustworthy melody-only or melody+accompaniment MusicXML/MuseScore score. Covers song-boundary splitting, scan-resolution tuning, non-destructive measure-length repair, anacrusis and tuplet correctness, melody selection, voice cleanup, and the fallback route of measuring the melody off the page when the OMR's rhythm cannot be repaired. Complements sheet2xml, which only runs the OMR engine.
allowed-tools: Read Bash Grep Glob Write Edit
argument-hint: [raw-omr-musicxml-or-source-pdf]
effort: medium
---

# Clean OMR Transcription

Turn raw Audiveris + music21 output into a score a musician can trust.

Two routes, and picking the wrong one is the most expensive mistake available
here. **Route A repairs the OMR file. Route B measures the melody off the page
and uses the OMR only for accompaniment.** Test one song both ways before
committing a book.

## Four rules that outrank everything

1. **Melody-note accuracy wins.** The scripts repair or report, never delete.
   When one reports a problem it cannot fix, decide; don't reach for a fix that
   trades notes for tidiness.
2. **Never pad a short bar with rests.** Padding makes every bar sum to its
   meter, so `verify_score.py` reports "0 problems" while notes and dots are
   missing — book 6 song 1 was delivered that way, verifying clean with four
   dropped dots and two absent notes. A short bar is a visible defect; a padded
   one is invisible. `--pad-holes` is for a score already reconciled. music21
   re-pads incomplete measures when it WRITES, so judge completeness from notes,
   never from a written file.
3. **Exhaust the repeats before reaching for the scan.** These books are
   strophic, and the OMR damages each statement of a phrase differently, so a
   damaged bar's correct reading is usually already in the file.
   `reconcile_repeats.py` recovered four of the eight bars a musician had to fix
   by hand in book 6 song 1, at no cost, and declined the other four rather than
   guess.
4. **Never invent rhythm.** Dots and tuplets must not appear where the source
   has none. Both arise the same way — a repair reaching for a longer note value
   to make a bar add up — and no check of measure length, note count or voices
   catches either. `normalize_measures.py` counts them before and after every run
   and reports an increase as `INVENTED`. Treat that as a defect;
   `references/rare-repairs.md` names the three repairs that can cause it.

Rules live in `scripts/`, not here. Run them; read them only if one misbehaves.
Paths below are relative to this skill's directory.

## Common first steps

```bash
# Before blaming OMR quality, check the scan geometry
scripts/fix_pdf_geometry.py book.pdf --report
scripts/fix_pdf_geometry.py book.pdf -o book_fixed.pdf   # if it says REBUILD

# Find where each song starts (you read the composites; see "your eyes")
scripts/find_title_bands.py book.pdf --out /tmp/bands --first-page 4

# Then Audiveris per song range (sheet2xml, or -sheets N-M on an .omr).
# Keep the .omr and raw exports NEXT TO THE BOOK, not in a session scratchpad:
# it is ~10 min of CPU and scratch gets wiped.
```

## Route A — repair the OMR

For when the OMR's rhythm is broadly right and the damage is measure-length
noise.

```bash
# If the melody SHARES a staff with the accompaniment (references/engraving.md)
scripts/split_shared_staff.py raw/song_01.mxl --out-base out/song_01

# Reconcile repeats BEFORE looking at the scan -- cheapest repair there is
scripts/reconcile_repeats.py out/song_01_melody_raw.musicxml --apply \
    -o out/song_01_melody.musicxml

scripts/normalize_measures.py raw/*.mxl --out-dir out --melody-only \
    --composer "..."

# Verify what was actually DELIVERED, including the .mscz if you ship one
scripts/verify_score.py out/*.musicxml --max-voices 1
scripts/verify_score.py out/*.mscz --max-voices 1
```

`normalize_measures.py` verifies its own output, so the last step matters most
for files that went through another tool (a `.mscz` round trip, a manual edit).
Both scripts exit non-zero on any problem, so they gate a loop.
`verify_score.py` also prints **rhythm suspects** — bars where a dot was probably
dropped. It names them; you settle them against the scan.
`references/reports.md` says what each report means.

## Route B — measure the melody off the page

For when the OMR's rhythm is not repairable: a printed duet, an engraving whose
dots Audiveris drops wholesale, a part assigned to the wrong staff. This is how
SMOM books 6 and 8 were delivered. The OMR is still used — for accompaniment
sonorities, and as a rhythm hypothesis to check against.

The melody becomes an explicit measured table (pitch, duration) and the score is
built from it, rather than repaired into existence. Per-book drivers live beside
the book; the general instruments are here:

```bash
scripts/songpass.py 15 --key -1        # ALL reconnaissance for one song
scripts/read_heads.py --page 24 --sys 1 --key -1 --x 0.30,0.40   # one window
scripts/pitchruler.py 24 1 --staff 0 --x 0.30,0.40 --n 2 -o /tmp/b.png
```

`songpass.py` first. For every system of every page a song occupies it reports
the real barlines, the noteheads grouped into bars (pitch, hollow/filled, dots,
stacks), the accompaniment clustered into named sonorities, and the OMR's own
skyline and per-offset accompaniment — then checks its bar count against the
OMR's and says whether they reconcile.

Keep the two readings side by side rather than merging them: **this kind of OMR
is reliable for rhythm and unreliable for pitch, octave, dots and accidentals;
the scan is the other way round.** Where they agree, a bar is settled with no
image at all. Where they disagree, that bar — and only that bar — is worth
rendering. A disagreement in the bar COUNT is information, not an error: on two
of four SMOM 8 songs tested it was the OMR that was wrong, and the page reading
matched the delivered table both times.

`OMR_SRC` selects the book PDF; `OMR_BOOK` the directory holding `song_map.tsv`
and the OMR exports (default: the working directory).

**Choosing between the routes:** read `references/engraving.md` first — whether
the melody has a staff of its own decides most of this. Then settle it on ONE
song run both ways and keep the loser as a second pass — two readings of the same staves disagree only where
one is wrong, so every difference is a bar to open the scan on. **Diff by note
sequence, not bar number**; one disagreement about a pickup shifts every later
bar.

## What needs your eyes

**Read the key signature off the page yourself, once per song, before anything
else.** Never inherit it from the OMR. One glance at the first system, and
getting it wrong is silent: the readers are *given* the key so they cannot
disagree, and a comparison in staff steps cannot either, since Bb and B natural
sit on the same line. One wrong signature quietly rewrites the piece and
everything built on it.

**Never read pitch off a small crop.** Comparing noteheads to each other by eye
turns a third into a second. Measure against the staff lines — `read_staff.py`
for a single line, `read_heads.py` for anything else. Both warn when a staff
space is under ~60px (re-render larger) or a reading lands between two pitches.
Rhythm is readable far smaller than pitch is, so a bar whose rhythm you have
confirmed is **not** thereby pitch-confirmed; check the two separately, per bar.

**Match the instrument to the question.** Cheapest to dearest: bar arithmetic, a
diff of two independent runs, measurement, a rendered image. Never render blind —
derive the crop window from a measurement first, or you will render the same bar
three times before it is legible.

| question | instrument |
|---|---|
| pitch, including dyads | `read_heads.py` — trust what it reports. It intermittently **misses hollow heads** (half notes, and a parenthesised ossia), at every dpi, so a bar that comes up empty or a half-note short means look |
| where the bars are | `songpass.py` (barlines minus notehead x positions) |
| an augmentation dot | `read_heads.py`, **good precision, partial recall**: one it reports can be trusted, one it does not report proves nothing. Close the bar by arithmetic, or look. |
| flags, beams, rests, slurs, ties | look at the page |
| which of two readings is right | render only the bars where they disagree |

Five things no script can settle:

1. **Song boundaries.** `find_title_bands.py` crops and stacks the bands; you
   read them — a scanned PDF has no text layer and the `.omr` usually has no OCR.
   Confirm each song runs from its numbered title to just before the next number
   up. A mid-page band that is a *title* (not lyrics) means a song starts mid-page
   and page ranges will cut songs in half. Watch for an unnumbered appendix, and
   exclude the staff-less pages it lists.
2. **Comparing a render against the scanned source.** The only check that catches
   a wrong pitch; structural checks never will. Sample songs with multiple
   "Voice" parts, irregular measures, or low OMR confidence.
3. **Any `INVENTED` report.** The count is automatic; judging whether a genuine
   increase is justified is not. The only legitimate one so far was a degenerate
   bar whose ornaments were unreadable until it was rescaled.
4. **Note-count deltas.** Raw vs final, per part. Expect legitimate movement — tie
   splitting inflates, collapsing duplicate-verse voices or unison doublings
   reduces. Localize before treating a delta as loss.
5. **Whether an advisory is worth chasing.** Check its precision before
   investigating a single flag; if false positives outnumber true ones (clef
   blobs, open noteheads, text above the staff), suppress those classes first.

## Defaults that are judgment calls

| Flag | Default | When the default is wrong |
|---|---|---|
| `--melody-only` | off | Pass it unless the piano is in scope: cheaper, and skips the voice-flattening that endangers tuplets. |
| `--anacrusis` | `auto` | `auto` unpads a rest-padded pickup only when pickup + final bar completes one bar. Shape alone can't tell a padded pickup from an opening bar written full. Use `always` if house style is that every upbeat is a short pickup bar. |
| `--no-triplets` | off | Tuplets are kept only where **obvious** — the engine tagged the run AND the bar already sums with it. An engine tag alone is not evidence: Audiveris emits tuplets as a by-product of misreading a bar. |
| `--min-trailing-rests` | 2 | Trailing all-rest bars are deleted once this many follow the last note. |
| `--max-voices` | 2 | Use 1 for melody-only. |

## Naming

`{BOOK_ABBR}_{book_number}_{song_number:02d}_{slug}_v{version}.musicxml`
(e.g. `SMOM_1_01_julafton_v1.musicxml`) — `omrlib.deliverable_name()` builds it.
`BOOK_ABBR` is the book title's initials, fixed once per series; `song_number` is
order of appearance **in the book**, not OMR sheet numbering; bump `version` when
replacing an already-delivered set with a materially different transcription, and
overwrite in place only while still iterating before hand-off.

**Rename per-song files only** — leave combined whole-book deliverables under
their existing names (confirm rather than assume). On a re-run, output names
derive from the *raw source* filename, so delete stale renamed files first
instead of expecting overwrites.

## Process notes

- `-sheets N-M` produces either `<bookname>.mxl` or `<bookname>.mvtnull.mxl` —
  check both, or every song silently overwrites the same scratch file. Audiveris
  ignores `-output` for `.omr` input and writes beside the book.
- Don't run Audiveris books in parallel; SYMBOLS/BEAMS throttle each other even
  with idle cores.
- Never raise Audiveris's `maxPixelCount` to allow native resolution — large
  images hit a hardcoded step timeout regardless of the pixel cap.

## Conditional references

- `references/engraving.md` — how a book is engraved, which staff finder to use,
  and the shared-staff route. Load before starting a new book.
- `references/reports.md` — what each reported problem means and what to do.
  Load when one fires.
- `references/multi-part.md` — grand staff and combined-book assembly. Load only
  when accompaniment or a whole-book score is in scope.
- `references/rare-repairs.md` — bars that resist the ordered repairs.
