---
name: transcribe-harmony
description: Use when a score already contains an accompaniment and the question is what harmony it STATES — reading the chords the piano or ensemble actually plays, bar by bar with inversions, into harmony_transcription.json or chord symbols on the score. The counterpart to analyze_music, which infers harmony a melody only implies. Does not read lyrics or alter the notes.
allowed-tools: Read Bash Grep Glob Write
argument-hint: [score-file-with-accompaniment]
effort: medium
---

# Skill: `transcribe_harmony`

## Purpose

Report the harmony a score already contains. Where `analyze_music` decides what
chords a melody *implies*, this one reads what the accompaniment *states*.
They are different jobs, with opposite obligations.

**Read, don't tidy.** `analyze_music` is a rulebook for choosing: prefer IV
after I, never resolve V to ii, land changes on strong beats, reject a chord
making parallel fifths. Every one of those is wrong here. The composer
already decided; a change on a weak beat, a V moving to ii, a bare parallel
fifth are all findings to report, not faults to correct. Applying the
strong-beat preference to a reading once turned a real beat-2 chord change into
a bar-long chord that was not in the source.

**The accompaniment is evidence the melody cannot give.** A bar whose melody
sits on degrees 3 and 5 fits both I and vi and inference has to guess; the piano
says which. Use this wherever that ambiguity matters, and treat a disagreement
with an inferred analysis as a bar to open, not a discrepancy to average.

## Inputs

```text
a score readable by music21 whose parts include an accompaniment
(.musicxml, .mxl, .mid) — typically a melody plus a piano grand staff
```

## Tools

### `../analyze_music/scripts/extract_basic_metadata.py`

Run this first, always — shared with `analyze_music`, and the only source for
tempo, meter and measure count:

```bash
python3 .claude/skills/analyze_music/scripts/extract_basic_metadata.py <score>
```

It reports only the *first* time signature, so check the score for mid-piece
changes, and recompute the measure count if an anacrusis shifts the barring.

### `scripts/accompaniment_chords.py`

Names the chord sounding in the accompaniment at each beat:

```bash
scripts/accompaniment_chords.py score.musicxml --key "G major" --check
scripts/accompaniment_chords.py score.mxl --key "D minor" \
    --json out.json --mscz melody.mscz --replace
```

Read its docstring only if it misbehaves. What matters at this level:

- `--melody-part N`, `--melody-ref FILE`, or auto-detection picks which part is
  the tune; everything else is treated as accompaniment.
- `--meter` and `--bar-offset` cover exports that lost their time signature or
  begin mid-piece — both happen when a page defeats the OMR engine.
- `--check` reports melody notes stranded under their chord, chords whose root
  is foreign to the key, and bars the engine read badly enough that a change
  cannot be placed correctly (`SUSPECT`) — an accompaniment that does not
  fill its bar, or whose onsets fall off the beat grid.
- `--restate` names a chord again at every beat it is in force. Off by
  default, which reports only where the harmony moves; use it when the
  score should carry a symbol on every beat regardless.
- `--replace` clears chord symbols already in a `.mscz`. It is never the
  default: it would discard hand corrections.
- Every chord carries a **fit** score. See step 4 — these are the whole point.

## Core responsibilities

1. Run `extract_basic_metadata.py` for tempo, meter and measure count.
2. **Determine the key from the accompaniment, not the melody.** This is the
   advantage the score gives you: the piano states its harmony outright, where a
   melody only implies one. Read the opening and closing chords and the
   cadences; a piece that opens and cadences on the relative minor is in that
   minor even if the melody's final note and the key signature suggest its
   relative major. Cross-check the signature, and check per section — a piece
   can state one key for its first half and another for its second. Settle this
   before deriving anything, because the key is part of the chord scoring.
3. Identify which part carries the melody and confirm it. Auto-detection
   picks the most monophonic part, which is wrong wherever the accompaniment
   is thinner than the tune. Prefer `--melody-ref` against a known score.
4. Derive the chords, then **work the fit scores**. A low fit means the window
   did not spell a chord cleanly; those bars get opened against the source.
   This is not optional and not a summary statistic: a signal that is computed,
   printed and never acted on is worse than none, because it looks like
   checking. If you do not open them, say so in the report.
   `--check`'s stranded-note test will not save you: a wrong chord closely
   related to the right one (the relative minor, say) still contains the
   melody notes and passes. A `SUSPECT` bar is different in kind — the
   input is damaged there, so no amount of scoring recovers it; report
   the chord as provisional or read that bar off the page yourself.
5. Sanity-check what survives. A chord whose root is foreign to the key may be
   real (a chromatic mediant at a climax, a passing diminished) or a misread
   accidental — decide by looking, not by rule. Misread accidentals in a flat
   key are the common case: impossible spellings like C-flat, or E-flat minor
   in a three-flat piece, mean that bar's reading is wrong.
6. Where an inferred analysis of the same piece exists, **diff the two**. Bars
   where they agree are solid; every disagreement is either a place inference
   guessed wrong or a place the accompaniment was misread, and both are worth
   knowing. Expect the accompaniment to change chord more often than inference
   does — that is detail, not disagreement.
7. Emit `harmony_transcription.json`, and optionally write the chords onto the
   score with `--mscz`.

## Output

`harmony_transcription.json`: the key and meter, then one entry per chord with
its measure, beat, symbol, bass and fit. Keep the fit scores in the output —
they are how a later reader knows which bars to distrust.

Report reliability per song rather than in aggregate. "6% of melody notes
stranded book-wide" hides the one song that is unusable; say which songs are
solid, which are mixed, and which should not be trusted.

## Failure modes

If no accompaniment part is found, say so rather than harmonising the melody —
that is `analyze_music`'s job, not this one. If the score has no time signature,
ask for `--meter` rather than guessing. If a page defeated the OMR engine and
its bars are missing, report the gap explicitly; silently transcribing the bars
that survived reads as a complete answer.
