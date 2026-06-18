---
name: mix-validate
description: Use when a vocal stem and an arranged score are ready to combine into a final mix. Renders the instrumental, aligns vocal timing, mixes levels, exports final_song.wav, and emits mix_report.json with timing, level, and musical conflict warnings.
allowed-tools: Read Bash Grep Glob Write
argument-hint: [musicxml-file] [vocal-wav]
effort: medium
---

# Skill 5: `mix_and_validate`

## Purpose

Render the instrumental arrangement, combine it with the vocal stem, and produce a validation report for timing, levels, and obvious musical conflicts.

## Inputs

```text
arranged_music.xml
vocal.wav
```

Usually `vocal.wav` is either:

```text
rough_vocal.wav
```

or:

```text
refined_vocal.wav
```

## Tools

### Instrument rendering

Use the existing MusicXML → MIDI → audio pipeline, or one of:

- `music21` for MusicXML/MIDI export
- MuseScore CLI for MusicXML rendering/export
- FluidSynth with a soundfont
- a DAW renderer such as REAPER/Ardour if already integrated

### Audio processing

Use one or more of:

- `ffmpeg`
- `sox`
- `pydub`
- `librosa`
- `soundfile`

For:

- trimming silence
- offset correction
- gain staging
- loudness/peak checking
- light reverb/compression if desired
- final export

### Validation

Use deterministic checks first. Optionally pass the structured report to an LLM for critique and next-step suggestions.

## Responsibilities

1. Render instrumental audio from `arranged_music.xml`.
2. Align vocal start time to the score timeline.
3. Mix vocal and instrumental levels.
4. Export `final_song.wav`.
5. Detect obvious issues:
   - vocal too quiet/loud
   - clipping
   - duration mismatch
   - long vocal gaps
   - dense high-register accompaniment under vocal
   - vocal range warnings from earlier metadata
6. Emit `mix_report.json`.

## Output

```text
final_song.wav
mix_report.json
```

Example report:

```json
{
  "files": {
    "instrumental": "instrumental.wav",
    "vocal": "refined_vocal.wav",
    "final": "final_song.wav"
  },
  "timing": {
    "vocal_start_seconds": 0.0,
    "detected_offset_warning": false,
    "instrumental_duration_seconds": 25.1,
    "vocal_duration_seconds": 24.8
  },
  "levels": {
    "vocal_peak_dbfs": -3.2,
    "instrumental_peak_dbfs": -4.5,
    "final_peak_dbfs": -1.0
  },
  "musical_warnings": [
    {
      "measure": 5,
      "type": "dense_accompaniment_under_vocal",
      "message": "High-register accompaniment may mask vocal consonants."
    }
  ],
  "suggested_next_actions": [
    "Lower flute by 6 dB in measures 5-6.",
    "Add a breath after measure 4."
  ]
}
```

## Why this output is useful

This skill closes the loop. The next LLM pass can use `mix_report.json` to decide whether to:

- change vocal alignment
- reduce accompaniment density
- rerun DiffSinger only
- rerun RVC only
- change mixing levels

## Suggested CLI

```bash
./bin/mix_and_validate arranged_music.xml refined_vocal.wav \
  --instrument-renderer fluidsynth \
  --soundfont soundfonts/default.sf2 \
  --out final_song.wav \
  --report mix_report.json
```

## Failure modes

Fail if:

- instrumental audio cannot be rendered
- vocal file missing or silent
- final mixed WAV cannot be written

Warn if:

- final audio clips
- vocal and instrumental durations differ too much
- vocal is likely masked by accompaniment
- vocal starts before the instrumental or after the expected entrance
