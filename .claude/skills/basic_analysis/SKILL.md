---
name: basic-analysis
description: Use when an arranged MusicXML score needs its foundational structure extracted — tempo, meter, key, measure count, anacrusis detection, part metadata, melody candidates, and phrase boundaries — as a prerequisite for harmonic analysis (analyze_music). Does not read lyrics, alter the score, or infer harmony.
allowed-tools: Read Bash Grep Glob Write
argument-hint: [musicxml-file]
effort: medium
---

# Skill: `basic_analysis`

## Purpose

Turn `arranged_music.xml` into the foundational, non-harmonic portion of a compact musical representation: global metadata, part metadata, melody candidates, and phrase boundaries. This is the prerequisite step for `analyze_music`, which adds the harmonic layer on top of this output.

This skill is structural-analysis-only. It should not read lyrics, should not alter the score, and should not infer harmony.

## Inputs

```text
arranged_music.xml
```

Optional config:

```json
{
  "preferred_vocal_range": ["C4", "A5"],
  "target_style": "gentle children's song",
  "language_hint": "English"
}
```

## Tools

### `scripts/extract_basic_metadata.py`

Run this first, always — it's a deterministic music21 script, not something to re-derive by reading/reasoning:

```bash
python3 scripts/extract_basic_metadata.py <path-to-musicxml>
```

Prints `tempo_bpm`, `meter`, `measure_count`, and per-part `name`, `range`, `note_count`, `density_score` as JSON. These fields are purely mechanical extractions with no musical judgment involved, so computing them via LLM reasoning is wasted token spend — this script is the only source for them. The one exception is `measure_count` when an anacrusis correction shifts the barring (step 2 below); recompute it from the corrected barring in that case rather than trusting the script's raw count.

### music21

For everything the script doesn't cover, use `music21` directly to:

- infer key
- find candidate melody lines
- compute singability features
- inspect note-duration patterns for the anacrusis check

## Core responsibilities

1. Parse the score and run `scripts/extract_basic_metadata.py` to get tempo, meter, measure count, and part name/range/density directly.
2. Determine the key, and check for a mis-notated anacrusis.
   - Don't trust the written barlines by default. Explicitly check the actual note-duration pattern at the start of the piece against the anacrusis shape every time — a short note or repeated pair of identical short notes (lighter-weight than what follows, or marked staccato) leading into a longer, more stable note — and treat a match as a possible mis-notated anacrusis (upbeat) rather than a downbeat. Do this check regardless of whether the opening measure contains a rest: a rest is one way an anacrusis gets mis-notated, but a measure that is already rhythmically "full" (no rest, adds up to the full bar) is just as capable of opening with this short-into-long shape, and its being metrically complete is not evidence the barline is already correct. Cross-check the hypothesis against the harmonic reading that `analyze_music` will perform downstream where possible (chord tones landing on strong beats instead of weak ones, fewer forced mid-measure splits, cadences/climaxes resolving onto harmonically logical chords rather than requiring an odd substitute); if a full harmonic re-derivation isn't practical at this stage, flag the ambiguity as a warning for `analyze_music` to resolve. If the melody contains a chromatic/leading-tone accidental, this is a decisive test: prefer the barring in which that note resolves forward onto the following downbeat, not one that strands it mid-measure after its resolution has already happened. If an anacrusis is confirmed, recompute `measure_count` from the corrected barring.
   - The piece's very first upbeat does not get its own measure number, even when it's a genuine, correctly-notated pickup (e.g. filled out with rests before it). Measure numbering starts at 1 with the first full measure; refer to the opening anacrusis separately (as the pickup/upbeat).
3. Determine each part's likely role (melody candidate vs. accompaniment) from its script-derived range and density, plus musical judgment (e.g. a single monophonic part is always the melody).
4. Identify melody candidates.
5. Estimate phrase boundaries.
   - Determine phrase boundaries from the melody's own signals first — rests, matching rhythmic/motivic units, repeated contours. Don't anticipate the harmonic analysis `analyze_music` will perform later; phrase grouping should stand on melodic evidence alone, so that skill can flag (rather than silently accommodate) any case where its harmony doesn't fit neatly into these boundaries.
6. Emit `basic_analysis.json`.

## Output

Write `basic_analysis.json` containing the `score` fields other than `harmony` (`tempo_bpm`, `meter`, `key`, `measure_count`, `parts`, `phrases`, `melody_candidates`), plus `warnings`. This is not standalone schema-valid `music_analysis.json` — `analyze_music` reads it, adds the `harmony` array, and re-emits the full `music_analysis.json` matching `schemas/music_analysis.schema.json`.

Example:

```json
{
  "score": {
    "tempo_bpm": 96,
    "meter": "4/4",
    "key": "C major",
    "measure_count": 16,
    "parts": [
      {
        "id": "P1",
        "name": "piano",
        "range": ["C3", "G5"],
        "role_guess": "accompaniment",
        "density_score": 0.72
      },
      {
        "id": "P2",
        "name": "flute",
        "range": ["C4", "A5"],
        "role_guess": "melody_candidate",
        "density_score": 0.31
      }
    ],
    "phrases": [
      {
        "id": "A1",
        "measures": [1, 4],
        "melody_candidate_part": "P2"
      }
    ],
    "melody_candidates": [
      {
        "source_part": "P2",
        "measures": [1, 8],
        "note_count": 32,
        "singability_score": 0.86,
        "range": ["C4", "G5"]
      }
    ]
  },
  "warnings": []
}
```

## Why this output is useful

`analyze_music` needs a settled structural foundation before it reasons about harmony:

- which part probably carries the tune
- where phrases start and end
- whether the melody fits a singable range
- how many melody notes are available
- the correct barring (anacrusis-adjusted) to harmonize against

## Suggested CLI

```bash
./bin/basic_analysis arranged_music.xml --out basic_analysis.json
```

## Failure modes

Return a nonzero exit code and diagnostic JSON if:

- MusicXML cannot be parsed
- no usable note material is found
- tempo cannot be determined and no default is supplied

If key or phrases are uncertain, emit warnings instead of failing.
