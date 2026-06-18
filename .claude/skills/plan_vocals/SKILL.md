---
name: plan-vocals
description: Use when music_analysis.json and lyrics.json are ready and syllables need to be aligned to melody notes to produce vocal_events.json for singing synthesis. This is the main LLM-assisted musical decision step.
allowed-tools: Read Bash Grep Glob Write
argument-hint: [music-analysis-json] [lyrics-json]
effort: high
---

# Skill 3: `plan_and_align_vocals`

## Purpose

Convert `music_analysis.json` + `lyrics.json` into `vocal_events.json`, the central representation for downstream singing synthesis.

This is the main LLM-assisted musical decision step.

## Inputs

```text
music_analysis.json
lyrics.json
```

Optional cue:

```text
gentle children's song, clear vocals, minimal melisma
```

## Tools

### LLM

Use the LLM to decide:

- which melody candidate should become the sung melody
- whether lyrics repeat across phrases
- whether to use one syllable per note or allow melismas
- where breaths should happen
- where vocals should rest
- whether the arrangement should thin out under the vocal
- whether the vocal range should be transposed

### Deterministic Python/music21 code

Use code to:

- extract exact notes from selected part/measures
- compute start beat and duration
- map notes to syllables
- validate that syllable count and note count are compatible
- prevent impossible outputs such as negative durations or missing pitches

## Core intermediate object

`vocal_events.json` should contain a flat list of sung events:

```json
{
  "global": {
    "tempo_bpm": 96,
    "meter": "4/4",
    "language": "English",
    "style": "gentle children's song"
  },
  "vocal_events": [
    {
      "id": "v001",
      "measure": 1,
      "start_beat": 1.0,
      "duration_beats": 1.0,
      "pitch": "C4",
      "lyric": "Twin",
      "word": "Twinkle",
      "line_id": "L1",
      "is_slur": false,
      "breath_after": false
    }
  ],
  "arrangement_notes": [],
  "warnings": []
}
```

## Alignment strategy

Prefer, in order:

1. **One syllable per melody note** when syllables $\ge$ notes.
2. When syllables $<$ notes, choose a subset of notes as **syllable-start anchors**, then mark intervening notes as slurred continuations (`is_slur = true`).
3. Do not repeat lyric text on slurred continuation notes (use an empty `lyric` field) to avoid accidental re-articulation.
4. Split long notes only if the backend or later MusicXML writer can represent the split cleanly.
5. Repeat short lyric fragments only when the cue explicitly asks for it.

### Anchor-note selection heuristic

When syllables $<$ notes, the deterministic code should pick anchor notes that are musically salient. A simple scoring rule works well:

- prefer longer durations
- prefer strong beats (beat 1 > beat 3 > beats 2/4)
- prefer phrase starts
- prefer large melodic leaps for new syllable starts
- penalize short repeated-pitch notes (often better as slur targets)

Then:

- force the first syllable to start on the first melody note
- distribute remaining anchors roughly evenly across the phrase (avoid placing all anchors early)

## LLM planning prompt shape

The LLM should receive:

- phrase summaries
- melody candidate summaries
- lyric lines with syllable counts
- cue/style
- constraints

The LLM should output a structured plan, not MusicXML.

Example plan:

```json
{
  "selected_melody_candidate": "P2:measures_1_8",
  "lyric_assignment": [
    {
      "phrase_id": "A1",
      "lyrics_line_ids": ["L1"],
      "strategy": "one_syllable_per_note_with_final_sustain"
    }
  ],
  "breath_after_measures": [4, 8],
  "arrangement_notes": [
    {
      "measure": 3,
      "issue": "flute doubles vocal melody",
      "suggestion": "reduce or remove flute while voice sings"
    }
  ]
}
```

Then deterministic code builds the final event list.

## Output

Write `vocal_events.json` matching `schemas/vocal_events.schema.json`.

## Why this output is useful

Everything after this step should be backend-independent.

If the result sounds wrong, the fix should usually happen here:

- wrong syllable timing → edit alignment
- awkward breath → edit `breath_after`
- too high/low → transpose vocal events
- bad melisma → edit `is_slur`

## Suggested CLI

```bash
./bin/plan_and_align_vocals music_analysis.json lyrics.json \
  --cue "gentle children's song, clear lyrics, no complex melismas" \
  --out vocal_events.json
```

## Validation checks

Warn if:

- vocal range exceeds configured target range
- more than 8 seconds pass without a breath opportunity
- lyrics are forced onto very short notes
- phrase has too many/few notes for its assigned lyric line
- accompaniment density is high in the vocal register
