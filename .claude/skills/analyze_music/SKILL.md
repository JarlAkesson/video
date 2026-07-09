---
name: analyze-music
description: Use when an arranged MusicXML score needs to be parsed into music_analysis.json — extracting tempo, meter, key, parts, phrases, melody candidates, and harmony — for downstream vocal planning. Does not read lyrics or alter the score.
allowed-tools: Read Bash Grep Glob Write
argument-hint: [musicxml-file]
effort: medium
---

# Skill 1: `analyze_music`

## Purpose

Turn `arranged_music.xml` into a compact musical representation that an LLM can reason over without reading raw MusicXML.

This skill is music-analysis-only. It should not read lyrics and should not alter the score.

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

## Core responsibilities

1. Parse the score.
2. Extract global metadata: tempo, meter, key, measure count.
   - Don't trust the written barlines by default. If the melody opens with a short note or repeated pair of identical short notes (lighter-weight than what follows, or marked staccato) leading into a longer, more stable note, treat that as a possible mis-notated anacrusis (upbeat) rather than a downbeat. Cross-check the hypothesis against the harmonic reading (step 6): re-derive the harmony under both the literal barring and the shifted-by-the-pickup barring, and prefer whichever produces the more idiomatic result — chord tones landing on strong beats instead of weak ones, fewer forced mid-measure splits, and cadences/climaxes resolving onto harmonically logical chords (tonic, dominant) rather than requiring an odd substitute. If the melody contains a chromatic/leading-tone accidental, this is a decisive test: prefer the barring in which that note resolves forward onto the following downbeat, not one that strands it mid-measure after its resolution has already happened.
3. Extract part-level metadata: instrument names, ranges, density, likely role.
4. Identify melody candidates.
5. Estimate phrase boundaries.
6. Infer harmonic context, preferably as chord symbols or roman numerals.
   - Respect standard functional root motion: tonic → predominant → dominant → tonic.
   - Never resolve a dominant chord (V, vii°) directly to a predominant chord (ii, IV). A dominant should move to tonic (or, if prolonged, to another dominant-function chord); if a predominant sonority is needed after it, treat the intervening melody notes as passing/neighbor tones over the surrounding chord instead of introducing a new predominant harmony.
   - For simple/nursery-style tunes, avoid assigning a chord that is dissonant with the melody note sounding above it — prefer the diatonic triad whose chord tones actually contain the melody note over one that only fits via an added 6th/9th or other color tone. This matters most for dominant chords: a clashing or colored dominant undercuts the cadential effect it's supposed to create. If no clean chord-tone fit spans a full measure, split the measure at the melodic change and assign each half its own (still consonant) chord rather than stretching one chord under a dissonant note. Exception: in minor/modal folk-style pieces, don't let this rule block a real V at a cadential moment just because the melody holds the tonic's minor 3rd (or another characteristic modal scale degree) against the chord's raised leading tone — that particular clash is a recognized, idiomatic feature of this style, not a fault, and is worth accepting when it completes a stronger cadential/harmonic-rhythm pattern (e.g. a regular i-V-i alternation).
   - Avoid oscillating back and forth between two predominant chords (e.g. IV-ii-IV-ii). This kind of back-and-forth doesn't progress anywhere and reads as awkward voice leading. When consecutive melody notes could each be harmonized by more than one predominant chord (e.g. a note that is a chord tone of both ii and IV), prefer holding a single sustained predominant harmony across the whole span over swapping chords back and forth.
   - Keep the harmonic rhythm regular (e.g. one chord change per measure, landing on the downbeat) rather than letting chord changes fall at irregular, arbitrary points mid-measure. When a melody note within the measure doesn't fit the prevailing chord as a plain chord tone, prefer reading it as a suspension, passing tone, or appoggiatura over that chord rather than triggering an early/off-beat harmony change. Reserve mid-measure chord changes for deliberate, consistently-placed harmonic acceleration into a cadence (e.g. splitting the measure right before a cadential resolution), not as a default way to accommodate every melody note.
   - When a melody note is a clean chord tone of both a predominant chord (ii, IV) and the dominant (V), prefer the dominant if using it would complete a stronger cadential progression (e.g. turning IV-ii-I into IV-V-I) or land the dominant at a structurally important arrival point, such as the retransition back into a returning phrase/section. A real authentic cadence (V-I) at these moments is usually more idiomatic than a plagal-style predominant-to-tonic resolution, and reusing the same dominant chord for every internal cadence keeps the piece's cadential vocabulary unified.
   - Once a ii chord is used, let it lead to V — do not resolve ii directly back to I. Unlike IV, which can idiomatically resolve straight to I (plagal motion), ii exists to prepare the dominant; "ii-I" is a red flag that V got skipped. Before finalizing a progression, check root motion legality and consistency with the harmonic rhythm already established elsewhere in the piece before reaching for a mid-measure split to fix a dissonant note — if the piece has been using one chord per full measure, prefer absorbing a non-fitting note as a decorative/passing tone within the expected whole-measure chord (matching the established root-motion and rhythmic pattern) over introducing a one-off split.
   - For any chord-to-chord move, check the candidate chord's root against the melody's motion, not just chord-tone consonance. If a chord's root is the same pitch as the melody note over it and both move in the same direction into the next chord's root/melody note, that's parallel unisons/octaves between "bass" and melody — reject the chord even if every melody note is a clean chord tone. This applies throughout the progression, not just at cadences.
   - Reserve dominant-function substitutes (vii°, and similar passing/leading-tone chords) for internal, non-final moments. At true structural cadences — especially the final cadence of the piece — prefer the actual V chord, so the bass gets the strong descending-5th root motion (5→1) into the tonic instead of the weaker stepwise approach a substitute chord gives.
   - When a melody note is a clean chord tone of more than one diatonic chord, don't default to whichever chord is already sustained out of inertia. Weigh the alternatives on their own merits: which gives the strongest root motion (e.g. a descending fifth) into the chord that follows, and — especially in a minor-key piece — whether a relative-major substitute (III for i, or similarly a major-mode substitute elsewhere) is equally well-supported by the melody and would add worthwhile color contrast instead of prolonging the same tonic chord by default.
7. Emit `music_analysis.json`.

## Output

Write `music_analysis.json` matching `schemas/music_analysis.schema.json`.

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
  "warnings": []
}
```

## Why this output is useful

The next skill needs to decide where and how to sing. It needs compact facts:

- which part probably carries the tune
- where phrases start and end
- whether the melody fits a singable range
- how many melody notes are available
- whether accompaniment conflicts with the vocal register

## Suggested CLI

```bash
./bin/analyze_music arranged_music.xml --out music_analysis.json
```

## Failure modes

Return a nonzero exit code and diagnostic JSON if:

- MusicXML cannot be parsed
- no usable note material is found
- lyrics are empty
- tempo cannot be determined and no default is supplied

If key, chords, or phrases are uncertain, emit warnings instead of failing.
