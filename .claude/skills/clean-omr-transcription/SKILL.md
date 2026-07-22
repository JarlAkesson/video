---
name: clean-omr-transcription
description: Use after Audiveris (or any OMR engine) has produced raw MusicXML from scanned sheet music, when the goal is a clean, trustworthy melody+accompaniment MusicXML/MuseScore deliverable. Covers scan-resolution tuning to avoid OMR failures, non-destructive rhythm normalization, melody-selection safety, voice/dynamics/chord-symbol cleanup, and time-signature deduplication. Complements sheet2xml (which only runs the OMR engine); this skill is the post-OMR cleanup pipeline.
allowed-tools: Read Bash Grep Glob Write Edit
argument-hint: [raw-omr-musicxml-or-source-pdf]
effort: high
---

# Clean OMR Transcription

This skill encodes lessons learned from transcribing multiple scanned songbooks
(Alice Tegnér "Sjung med oss, mamma!", books 1-5) with Audiveris + music21.
Follow it whenever the task is: turn raw, messy OMR output into a MusicXML
score a musician can trust, especially when melody accuracy is the priority.

## Governing principle

**Melody-note accuracy is the highest priority.** Every rule below exists to
either preserve real notes or remove genuine noise — never to guess-and-hope.
When in doubt, prefer leaving ambiguous content untouched and reporting it
over silently "fixing" it in a way that could delete or alter a real note.

## 1. Fix scan resolution and page geometry BEFORE blaming OMR quality

If Audiveris throws "Too large image", times out on `BEAMS`/`GRID`, or
produces suspiciously wrong notes, check the source PDF's page geometry
before assuming the engine is simply bad at this piece.

- Audiveris rasterizes based on the **PDF's declared physical page size**
  (in points), not the embedded image's raw pixel count. A PDF with a
  bloated declared page size (e.g. 40x27 inches) but a modest embedded image
  forces Audiveris to upsample internally — causing blur, slow processing,
  and an internal per-step timeout (not just the "too large image" pixel-count
  rejection).
- Fix: rebuild the PDF with a **correct, sane physical page size** (compute
  a target `points-per-pixel` empirically from a known-good page, e.g.
  `~4.12 px/pt`, and size the page from the native image resolution) so
  Audiveris's internal rasterization lands near native resolution instead of
  upsampling.
- Separately, **upsampling the embedded image itself** (e.g. to ~18M total
  pixels via PyMuPDF, safely under Audiveris's default 20M-pixel cap) measurably
  improves recognition accuracy even when it adds no new real information —
  likely because it changes anti-aliasing/binarization behavior. Test this
  on one representative page first (compare note-for-note against a
  known-correct rendering or the source image) before committing to a full
  reprocessing run.
- Never raise Audiveris's `maxPixelCount` constant to allow true native
  resolution as a shortcut — very large images can hit a hardcoded internal
  step timeout regardless of the pixel-count cap.

## 2. Rhythm/duration normalization must be PAD-ONLY, never destructive

This is the single most important rule. A prior pass used a "fix measure
duration to match the time signature" step that **trimmed/deleted real notes**
when a measure appeared too long — this caused severe, silent note loss
(e.g. -21 piano notes in one song) that was invisible to duration-only checks.

- If a measure's actual content is **shorter** than the expected duration for
  its time signature: pad with rests. Safe.
- If a measure's actual content is **longer** than expected: **leave it
  completely untouched** and report it as informational only. Do not shorten,
  do not delete trailing notes, do not force-fit. An "overlong" measure
  usually means either genuine irregular meter or an OMR ambiguity — guessing
  which and cutting is worse than leaving real content alone.
- When reconstructing a `Duration` object during timing cleanup, always build
  a **fresh** `Duration(quarterLength=...)`, never mutate `.quarterLength` in
  place — stale `Tuplet` metadata surviving in-place mutation corrupts
  MusicXML export even when the numeric duration looks correct.
- Watch for "complex" durations: `music21.duration.Duration(quarterLength=X).type`
  can be `'complex'` for values like 2.5 that aren't a single notatable
  symbol. The MusicXML exporter cannot serialize these directly — split them
  into simple tied notes (`Duration.components`) rather than letting the
  writer crash or silently mis-render.
- A voice whose first note starts mid-measure (e.g. offset 2.5 in a fresh
  measure) is invalid/ambiguous for export — fill the leading gap with
  properly-decomposed simple rests, not a single complex-duration rest.
- Time-signature inference: if a part has a time signature only starting
  partway through the piece (Audiveris often misses the very first system's
  header), backfill that signature onto the earlier measures too, rather than
  leaving them with no expected duration (which both skips validation and can
  trip music21's own `makeRests`/`makeTies` on write).

## 3. Melody selection must never silently pick the wrong part

When Audiveris splits a single vocal staff into multiple spurious "Voice"
parts (common with multi-verse hymnal engravings — one melody line, several
stacked lyric verses), it does NOT mean multiple real melodies exist.

- Never assume the first "Voice"-named part is the real melody. Compare all
  "Voice" parts' note counts and pick the one with the most actual notes —
  the first one Audiveris happens to emit can be nearly empty while the real
  47-note tune is in a later part.
- Route the non-chosen "Voice" parts into the accompaniment pool rather than
  discarding them — they may carry genuine chordal/harmonic content.
- When melody has to be extracted from a piano right-hand part (no dedicated
  Voice part exists), always exclude that consumed RH part from the
  accompaniment — otherwise the melody gets silently duplicated into the
  accompaniment staff.

## 4. Voice count and cleanliness inside a staff

Real engravings for simple songs (solo melody + piano accompaniment) never
have more than 2 simultaneous real voices in a single staff. Audiveris
routinely over-segments:

- **Remove any Voice sub-stream that contains no real (non-rest) note** —
  pure OMR noise, never genuine content, regardless of how many voices
  remain afterward.
- **If more than 2 real (non-empty) voices remain in one measure**, consolidate
  down to 2. This happens when Audiveris splits one genuine musical line
  (e.g. a sustained bass note) into 2+ voice fragments that don't even fully
  overlap in time. Sort voices by real-note count, keep the top 2, and merge
  every note from the excess voices into whichever of the 2 kept voices has
  no timing conflict at that note's span — this preserves every real note
  rather than discarding any of them.
- Apply the empty-voice removal and consolidation pass **twice**: once during
  per-song processing, and again as a final safety pass on the fully
  assembled combined score. Multi-song assembly (re-flattening voice IDs
  across song boundaries) can reintroduce a stray empty/extra voice that was
  already clean in the per-song file.
- **Also re-check after the final `.write('musicxml', ...)` call.**
  music21's own MusicXML writer can itself introduce a spurious extra/empty
  voice at serialization time (an internal backup/rest-fill quirk for voices
  that don't span the full measure identically) — even when the in-memory
  score was verified clean immediately before the write. The reliable fix:
  re-parse the file that was just written, run the cleanup pass again, and
  rewrite. Don't trust an in-memory check alone as proof the file on disk is
  clean.

## 5. Strip markings that don't belong unless explicitly requested

Unless the user asks for harmonic analysis, dynamics, or chord symbols:

- **Remove all `Dynamic` markings** (`p`, `f`, `mf`, etc.) picked up by OMR —
  these are noise from the scan, not something to preserve by default for a
  clean transcription pass.
- **Remove all `ChordSymbol` annotations.** If a prior pass added
  chord-symbol/harmonic-analysis derivation and the user says "there are too
  many mistakes, don't do that yet" — remove that pipeline stage entirely for
  this round rather than trying to patch it. Harmonic analysis is a separate,
  higher-risk step; do it only when explicitly requested and validated on its
  own.
- **Keep fermata-stripping** (`strip_fermatas`) as a default cleanup step —
  OMR-recognized fermatas over barlines/rests are usually spurious for
  strophic songs.

## 6. Time signatures: only stamp what should be visible

Internally, duration-validation logic needs a time signature carried forward
onto every measure so it always has something to compare actual duration
against. That internal bookkeeping value must NOT leak into the final
notation.

- Keep an explicit `TimeSignature` only on **the first measure of each song**
  and on **genuine meter changes** (where the ratio string actually differs
  from the previous measure's).
- Run this de-duplication as the **very last step before writing**, after all
  duration math is done — deduplicating too early causes measures without an
  explicit signature to be skipped by validation logic that only reads
  `mm.timeSignature` directly (rather than the carry-forward-aware
  `effective_time_signatures` helper).
- Apply de-duplication to both the per-song files and the final combined
  score.

## 7. Grand staff structure

- Build accompaniment as a true single Piano instrument with a braced grand
  staff: use `music21.stream.PartStaff` (not plain `Part`) for each hand,
  joined via `layout.StaffGroup([rh, lh], symbol='brace')`. This serializes
  as ONE `<score-part>` with `<staves>2</staves>`, not two separate
  instruments.
- Strip any leftover `Instrument` objects (e.g. a stray "Voice Oohs"
  instrument tag inherited from a source part that got repurposed as
  accompaniment) and explicitly set `instrument.Piano()` on each hand —
  otherwise some readers (MuseScore) display or sound the wrong instrument
  name even though `partName` was correctly overridden.

## 8. Validation checklist before calling a book "done"

Never trust structural checks alone (duration math, fermata counts, note
counts) as proof the melody is correct — none of those catch "picked the
wrong Voice part" or "note pitch is simply wrong." Before reporting success:

1. Confirm zero empty voices and max-2-voices-per-staff, post-write (re-parse
   the actual output file, don't just check in-memory state).
2. Confirm zero unwanted Dynamics/ChordSymbols if the user asked for a clean
   pass.
3. Confirm time signatures appear only at genuine starts/changes.
4. **Visually compare a sample of songs against the actual scanned source
   pages** — render the MusicXML (MuseScore CLI or equivalent) and eyeball
   it against the corresponding source image, especially for any song
   flagged with multiple "Voice" parts, irregular measures, or low OMR
   confidence in the log. Structural cleanliness is necessary but not
   sufficient for "melody is correct."
5. Re-run note-count comparisons between the raw OMR export and the final
   processed file per song — a large unexplained delta (either direction) is
   a red flag worth investigating before trusting the result.

## 9. File naming convention

Once a book's songs are cleaned and finalized, rename each per-song deliverable
to a stable, sortable convention rather than leaving Audiveris's source-derived
names (`song_NN_sheets_X_v6.musicxml`) in place:

```
{BOOK_ABBR}_{book_number}_{song_number:02d}_{slug}_v{version}.musicxml
```

- `BOOK_ABBR`: initials of the book title (e.g. `SMOM` for "Sjung med oss,
  mamma!"), decided once per songbook series and reused across all of its
  volumes.
- `book_number`: the volume number within the series (`1`, `2`, `3`, ...).
- `song_number`: two-digit, zero-padded, reflecting the song's **order of
  appearance in the book** — not any OMR sheet/page numbering.
- `slug`: the song title, lowercased and slugified — strip any leading
  `"N. "` numbering prefix from the title first, then
  `unicodedata.normalize('NFKD', title)` → ascii-encode (drop non-ascii,
  e.g. accented Swedish letters) → lowercase → replace runs of non-alphanumeric
  characters with `_` → strip leading/trailing `_`.
- `version`: the pipeline-version counter for that song. When a naming
  convention is introduced or changed, treat it as a fresh start and restart
  numbering at `v1` for every song rather than trying to preserve old version
  numbers across the rename.

Example: `SMOM_1_01_julafton_v1.musicxml`.

**Only rename the individual per-song files.** Leave any combined whole-book
deliverable (e.g. `Alice_Tegner_Sjung_med_oss_mamma_{N}_combined.musicxml` /
`.mscz`) under its existing name — this is a deliberate, explicit choice
(confirmed with the user rather than assumed), since the combined file is
typically referenced by that name elsewhere and doesn't benefit from
per-song ordering metadata.

When applying (or re-applying) this rename after a pipeline re-run: the
per-song output filenames on disk always come from the *raw source* filename
(e.g. `song_02_sheets_5.mxl` → `song_02_sheets_5_v6.musicxml`), not from the
previous rename — so if the pipeline runs again, delete stale renamed files
first (or regenerate the mapping fresh from the script's `SONGS` list) rather
than assuming yesterday's `SMOM_*` names will just get overwritten in place.

## 10. Cross-part measure-number gaps — a root cause of severe combined-score corruption

Beyond simple measure-*count* mismatches (covered by re-syncing counts), watch
for a subtler and more dangerous OMR artifact: one part's measures are
numbered with a **gap relative to another part**, e.g. Melody has measures
`1..9` but the Piano part (Audiveris misdetected/mislabeled a pickup bar) has
measures `2..10` — same *count* (9), but the wrong numbers, with the
implied content shifted by one position.

- Fixing this by only checking `len(measures)` and padding a rest measure
  **at the end** is wrong and dangerous: it hides the count mismatch while
  leaving the actual position of every subsequent measure silently shifted
  by one. When per-song scores are later appended positionally into a
  combined book-length score, this shift compounds across every remaining
  song and can balloon into gross corruption (observed: a piano PartStaff
  correctly at 301 measures ballooning to 418 after assembly+write, because
  one mid-book song's gap desynced everything appended after it).
- The correct fix: use one part's actual measure **numbers** as the reference
  sequence (pick the part with the most measures), find which numbers are
  *missing* from each other part, and insert rest-padding measures at the
  correct ordinal position in that sequence — not always at the end.
- This class of bug is easy to miss because each individual per-song file
  still looks locally consistent (`[9, 9, 9]` measures across parts) — the
  corruption only becomes visible after combining many songs together, so
  don't treat "per-song counts match" as sufficient proof of correctness;
  always also verify the final combined score's per-part measure counts
  match exactly.

## 11. music21's MusicXML writer is not idempotent — guard the final write, don't just loop it

Re-parsing and rewriting an already-written file is not a safe way to "clean
up" residual issues — music21's own MusicXML export step can itself
introduce corruption that wasn't present in the verified-clean in-memory
score, in at least two distinct ways:

- **Spurious empty/extra voice**: a measure that was verified to have ≤2 real
  voices immediately before `.write()` can come back with an extra
  rest-only voice when the just-written file is re-parsed.
- **Measure-count inflation**: a grand-staff `PartStaff` part can silently
  gain far more measures than its sibling parts on write (observed: 301 →
  418), with music21 raising no error at all.

Both are non-deterministic in the sense that they don't reproduce from every
input, but for a given score+write they are **deterministic** — repeatedly
re-parsing and rewriting the *same already-corrupted file* does not
reliably converge, and can make measure-count inflation worse, not better,
since each rewrite operates on an already-inflated input.

The robust pattern:
1. Do all cleanup on the **original in-memory score** before ever writing.
2. Write once, then re-parse the result and check both (a) voice violations
   and (b) that every part's measure count matches the in-memory reference
   counts taken before the write.
3. If check (b) fails (measure-count mismatch), retry by writing the
   **original in-memory score again from scratch** — never from the
   corrupted file — since only a fresh write has a chance of not hitting
   the same inflation path. Cap retries (e.g. 5 attempts) and warn if it
   never converges.
4. If only check (a) fails (voice violations, counts otherwise consistent),
   it's then safe to re-parse the written file, clean voices in place, and
   do one final rewrite — this residual case is a much smaller, more
   localized defect than a full measure-count desync.
5. Accept that a small number of measures may resist even this and require
   a manual fix in a notation editor (e.g. MuseScore GUI: select the stray
   empty voice's rest and remove it) — confirm this tradeoff with the user
   rather than silently shipping a corrupted file or looping indefinitely.

## 12. Practical process notes

- When re-exporting individual songs from a completed Audiveris `.omr`
  checkpoint via `-sheets N-M`, check for **both** `<bookname>.mxl` and
  `<bookname>.mvtnull.mxl` as the output filename — Audiveris picks one or
  the other depending on whether it detected multiple "Score" objects, and
  copying only ever checking the plain name will silently overwrite the same
  scratch file across every song, losing all but the last one.
- Long-running OMR batches: running multiple books' Audiveris processes in
  parallel can look fine at first but severely throttle each other's
  throughput on CPU-heavy steps (SYMBOLS/BEAMS) even on a machine with idle
  cores — if progress mysteriously stalls under parallel load, kill down to
  one process at a time and compare throughput before assuming something is
  broken.
- Save reusable pipeline scripts to a durable project path (not `/tmp` or a
  session scratchpad) — scratch directories can be wiped between turns,
  losing in-progress work with no warning.
