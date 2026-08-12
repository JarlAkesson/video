---
name: clean-omr-transcription
description: Use after Audiveris (or any OMR engine) has produced raw MusicXML from scanned sheet music, when the goal is a clean, trustworthy melody+accompaniment MusicXML/MuseScore deliverable. Covers scan-resolution tuning to avoid OMR failures, non-destructive rhythm normalization, melody-selection safety, voice/dynamics/chord-symbol cleanup, and time-signature deduplication. Complements sheet2xml (which only runs the OMR engine); this skill is the post-OMR cleanup pipeline.
allowed-tools: Read Bash Grep Glob Write Edit
argument-hint: [raw-omr-musicxml-or-source-pdf]
effort: medium
---

# Clean OMR Transcription

Turn raw Audiveris + music21 output into a score a musician can trust.

**Governing principle: melody-note accuracy wins.** Preserve real notes or
remove genuine noise — never guess-and-hope. Leave ambiguous content untouched
and report it rather than "fixing" it.

## 1. Scan resolution

Before blaming OMR quality for "Too large image", `BEAMS`/`GRID` timeouts, or
wrong notes, check the source PDF's geometry.

- Audiveris rasterizes from the PDF's **declared physical page size**, not the
  embedded image's pixel count. A bloated declared size (e.g. 40x27 in) forces
  internal upsampling → blur, slowness, per-step timeouts.
- Fix: rebuild the PDF at a sane page size (derive points-per-pixel empirically
  from a known-good page, e.g. `~4.12 px/pt`).
- Separately, upsampling the **embedded image** to ~18M px (under Audiveris's
  20M cap) measurably improves accuracy. Test one page against the source
  before a full reprocess.
- Never raise `maxPixelCount` — large images hit a hardcoded step timeout
  regardless of the pixel cap.

## 2. Rhythm normalization is PAD-ONLY

Never trim or delete to make a measure fit its time signature — that causes
silent note loss invisible to duration-only checks.

- Measure shorter than expected → pad with rests.
- Measure longer than expected → **leave untouched**, report as informational.
- Build a **fresh** `Duration(quarterLength=...)`; never mutate `.quarterLength`
  in place (stale `Tuplet` metadata corrupts export).
- `Duration.type == 'complex'` (e.g. qL 2.5) cannot serialize — split via
  `Duration.components` into tied simple notes.
- A voice starting mid-measure is invalid — fill the leading gap with
  decomposed simple rests, not one complex rest.
- If a time signature first appears partway through, backfill it onto earlier
  measures (Audiveris often misses the first system's header).

## 3. Melody selection

Multiple spurious "Voice" parts (common with multi-verse hymnals) do not mean
multiple melodies.

- Pick the "Voice" part with the **most real notes**, never the first one —
  Audiveris's first can be nearly empty.
- Route non-chosen "Voice" parts into the accompaniment pool, don't discard.
- If melody comes from a piano RH part, exclude that part from accompaniment
  or the melody is duplicated.

## 4. Voices

Solo melody + piano never has more than 2 real voices per staff.

- Remove any Voice sub-stream with no non-rest note.
- If >2 real voices remain in a measure: sort by real-note count, keep the top
  2, and merge notes from the excess into whichever kept voice has no timing
  conflict at that span — preserve every note.
- Run this pass twice: per-song, and again on the assembled combined score
  (re-flattening voice IDs can reintroduce strays). Also re-check post-write
  (see §10).

## 5. Strip unrequested markings

Unless the user asks for them, remove all `Dynamic` and `ChordSymbol` objects,
and strip fermatas by default (OMR fermatas over barlines/rests are usually
spurious for strophic songs). Harmonic analysis is a separate, higher-risk
step — do it only when explicitly requested.

## 6. Time signatures

- Keep an explicit `TimeSignature` only on the **first measure of each song**
  and on genuine meter changes (ratio string differs from previous).
- De-duplicate as the **very last step before writing** — earlier, and
  validation logic reading `mm.timeSignature` directly will skip measures.
- Apply to both per-song files and the combined score.

## 7. Grand staff

- Use `stream.PartStaff` per hand joined by
  `layout.StaffGroup([rh, lh], symbol='brace')` → one `<score-part>` with
  `<staves>2</staves>`.
- Strip leftover `Instrument` objects and set `instrument.Piano()` explicitly,
  or MuseScore shows the wrong instrument despite a correct `partName`.

## 8. Cross-part measure-number gaps

Watch for parts with matching measure *counts* but mismatched *numbers*
(Melody `1..9` vs Piano `2..10`). Padding a rest measure at the **end** hides
the mismatch while shifting every measure's position — which compounds across
songs during combined-score assembly into gross corruption.

- Correct fix: take the part with the most measures as the reference number
  sequence, find which numbers each other part is missing, and insert padding
  at the correct **ordinal position**.
- Per-song counts matching is not proof — always verify the final combined
  score's per-part counts too.

## 9. Naming

`{BOOK_ABBR}_{book_number}_{song_number:02d}_{slug}_v{version}.musicxml`
(e.g. `SMOM_1_01_julafton_v1.musicxml`)

- `BOOK_ABBR`: initials of the book title, fixed once per series.
- `song_number`: zero-padded order of appearance **in the book**, not OMR
  sheet numbering.
- `slug`: strip any leading `"N. "` from the title, then
  `unicodedata.normalize('NFKD', ...)` → ascii-encode (drop non-ascii) →
  lowercase → runs of non-alphanumerics to `_` → strip edge `_`.
- `version`: restart at `v1` whenever the convention changes.

**Rename per-song files only.** Leave combined whole-book deliverables under
their existing names (confirm with the user rather than assuming). On a
pipeline re-run, output names derive from the *raw source* filename, so delete
stale renamed files first instead of expecting overwrites.

## 10. The MusicXML writer is not idempotent

music21's export can introduce a spurious empty voice, or inflate a
`PartStaff`'s measure count (observed 301 → 418) with no error. Re-parsing and
rewriting a corrupted file does not converge and can make inflation worse.

1. Do all cleanup on the **original in-memory score** before writing.
2. Write once; re-parse and check (a) voice violations and (b) every part's
   measure count against in-memory reference counts taken before the write.
3. If (b) fails, rewrite the **original in-memory score** from scratch — never
   the corrupted file. Cap retries (~5) and warn if it never converges.
4. If only (a) fails, it is safe to re-parse, clean voices in place, rewrite.
5. If a few measures still resist, confirm a manual MuseScore fix with the
   user rather than looping or shipping corruption.

## 11. Validation before calling a book done

Structural checks never catch "wrong Voice part" or "wrong pitch."

1. Zero empty voices, max 2 voices/staff — verified by re-parsing the output
   file, not in-memory state.
2. Zero unwanted Dynamics/ChordSymbols.
3. Time signatures only at genuine starts/changes.
4. **Render a sample and eyeball it against the scanned source pages**,
   especially songs with multiple "Voice" parts, irregular measures, or low
   OMR confidence.
5. Compare per-song note counts, raw OMR vs final — investigate any large
   unexplained delta in either direction.

## 12. Process notes

- Re-exporting via `-sheets N-M` produces either `<bookname>.mxl` or
  `<bookname>.mvtnull.mxl` — check both, or every song silently overwrites the
  same scratch file.
- Don't run Audiveris books in parallel; CPU-heavy steps (SYMBOLS/BEAMS)
  throttle each other even with idle cores.
- Save pipeline scripts to a durable project path, never `/tmp` or a session
  scratchpad.
