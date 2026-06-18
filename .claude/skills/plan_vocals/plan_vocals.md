# Skill 2: `plan_and_align_vocals`

## Purpose

Convert `analysis.json` into `vocal_events.json`, the central representation for downstream singing synthesis.

This is the main LLM-assisted musical decision step.

## Inputs

```text
analysis.json
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

1. One syllable per melody note.
2. Stretch one syllable over multiple notes using `is_slur = true` for continuation notes.
3. Split long notes only if the backend or later MusicXML writer can represent the split cleanly.
4. Repeat short lyric fragments only when the cue explicitly asks for it.

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
plan_and_align_vocals analysis.json \
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
