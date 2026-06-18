# Skill 1: `analyze_inputs`

## Purpose

Turn `arranged_music.xml` and `lyrics.txt` into a compact musical representation that an LLM can reason over without reading raw MusicXML.

This skill is analysis-only. It should not alter the score.

## Inputs

```text
arranged_music.xml
lyrics.txt
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

### music21

Use `music21` to:

- parse MusicXML
- list parts and instruments
- extract measures, notes, rests, voices, and durations
- infer key and meter
- read tempo markings
- chordify the arrangement to infer harmonic context
- find candidate melody lines
- compute ranges and singability features

### Lyric processing tools

Use one or more of:

- `pronouncing` for English CMU-dictionary-based phoneme/stress information
- `g2p-en` for English grapheme-to-phoneme
- `pyphen` for rough syllabification
- LLM fallback for language detection, punctuation cleanup, syllable splitting, and children-song-style phrasing

## Core responsibilities

1. Parse the score.
2. Extract global metadata: tempo, meter, key, measure count.
3. Extract part-level metadata: instrument names, ranges, density, likely role.
4. Identify melody candidates.
5. Estimate phrase boundaries.
6. Infer harmonic context, preferably as chord symbols or roman numerals.
7. Parse lyrics into lines and syllables.
8. Emit `analysis.json`.

## Output

Write `analysis.json` matching `schemas/analysis.schema.json`.

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
        "cadence_guess": "half cadence",
        "melody_candidate_part": "P2"
      }
    ],
    "harmony": [
      {
        "measure": 1,
        "beat": 1.0,
        "chord_guess": "I"
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
  "lyrics": {
    "language": "English",
    "lines": [
      {
        "id": "L1",
        "text": "Twinkle twinkle little star",
        "syllables": ["Twin", "kle", "twin", "kle", "lit", "tle", "star"],
        "syllable_count": 7
      }
    ]
  },
  "warnings": []
}
```

## Why this output is useful

The next skill needs to decide where and how to sing. It needs compact facts:

- which part probably carries the tune
- where phrases start and end
- whether the melody fits a singable range
- how many melody notes are available
- how many lyric syllables need placement
- whether accompaniment conflicts with the vocal register

## Suggested CLI

```bash
analyze_inputs arranged_music.xml lyrics.txt \
  --language English \
  --style "gentle children's song" \
  --out analysis.json
```

## Failure modes

Return a nonzero exit code and diagnostic JSON if:

- MusicXML cannot be parsed
- no usable note material is found
- lyrics are empty
- tempo cannot be determined and no default is supplied

If key, chords, or phrases are uncertain, emit warnings instead of failing.
