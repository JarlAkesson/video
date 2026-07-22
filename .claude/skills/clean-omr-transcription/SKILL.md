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

## 9. Practical process notes

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
