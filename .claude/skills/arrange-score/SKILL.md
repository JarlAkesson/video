---
name: arrange-score
description: Use when the user wants to transform or augment an existing symbolic score. Arranges MusicXML into a new styled score using preferences such as vibe, instruments, key, tempo, density, groove, bass, and drums while preserving score editability.
allowed-tools: Read Bash Grep Glob Write
argument-hint: [musicxml-or-mxl-file]
effort: high
---

# Arrange Score

Create a new arranged `MusicXML` score from an existing `.musicxml` or `.mxl` file.

The canonical output of this skill is editable `MusicXML`, not MIDI.

Use this skill when the user wants to:

- add instruments such as violin, cello, strings pad, bass, or drumset
- restyle a score toward a vibe such as dark hiphop, cinematic strings, chamber additive, or lo-fi sparse
- change key or tempo while keeping the piece recognizably related to the source
- build a new arrangement that remains score-like and editable

## Output

Write the arranged score under:

```text
assets/_build/xml/
```

Use a deterministic filename:

```text
assets/_build/xml/<basename>.<tag>.musicxml
```

## Input model

The user may provide:

- a source score path
- a short freeform goal such as `dark hiphop remix with swagger`
- an optional compact preference block

Translate user preferences into the arranger script flags.

Required concepts:

- `source_score`
- `goal`

If the user only names a source score and does not give arrangement preferences, ask one concise follow-up before running the skill.

Good fallback question shape:

- desired vibe or preset
- added instruments, if any
- whether to keep or change key and tempo

Do not silently assume a genre restyle when the user has not said what kind of arrangement they want.

Optional preferences:

- `preset`: `none | hiphop_dark | cinematic_strings | chamber_additive | lofi_sparse`
- `target_key`: `keep | <named key> | transpose:<semitones>`
- `tempo`: `keep | slower:<percent> | faster:<percent> | bpm:<number>`
- `add_instruments`
- `remove_instruments`
- `vibe`
- `energy`: `low | medium | high`
- `density`: `sparse | medium | dense`
- `groove`: `straight | swung | halftime | syncopated`
- `bass`: `none | light | strong`
- `drums`: `none | restrained | strong`
- `entry_after_bars`: integer or `auto`
- `melody_treatment`: `preserve | shadow | decorate | counter`
- `harmony_treatment`: `preserve | color | darker`
- `register_shift`: `none | lower | higher`
- `expression`: `plain | shaped | assertive`

Supported added instruments in v1:

- `violin`
- `cello`
- `strings_pad`
- `bass`
- `drumset`

## Workflow

1. Resolve the input score path from `$ARGUMENTS`.
2. Read the user goal and preference hints.
3. If the user gave only a source path or an underspecified request like `use the skill on X`, ask one concise follow-up for arrangement preferences before continuing.
4. Normalize the request into arranger flags.
5. Run `scripts/arrange_score.py`.
6. Validate that the output MusicXML exists and is parseable.
7. Report:
   - input score
   - output score
   - resolved preferences
   - parts added or removed
   - key and tempo changes
   - any limitations triggered by the heuristics

## Preference resolution

Use this precedence:

1. explicit structured preferences
2. freeform goal inference
3. preset defaults
4. global defaults

Reasonable defaults:

- preserve source parts unless explicitly removed
- keep key unless a preset defines a shift
- keep tempo unless a preset defines a scaling
- infer `add_instruments` from the preset only when the user did not specify instruments

If the user requests unsupported instruments, say so briefly and map to the nearest supported family when reasonable.

## Script usage

Typical invocation shape:

```bash
python3 scripts/arrange_score.py /abs/path/input.mxl \
  --goal "dark hiphop remix with swagger" \
  --preset hiphop_dark \
  --density sparse \
  --groove halftime \
  --bass strong \
  --drums strong
```

Use comma-separated values for lists:

```bash
--add-instruments violin,bass,drumset
--remove-instruments piano
```

If the user later wants playback artifacts, pass the arranged MusicXML to:

- `xml2midi` for MIDI export
- `midi2music` for rendered audio

Do not make MIDI the primary output of this skill.

## Validation

Minimum validation:

- output file exists
- output XML parses
- part list and part bodies are consistent
- each measure in each part sums to the expected duration

If MuseScore CLI is available and a quick sanity check is useful, exporting the arranged XML to MIDI is a good interop test, but it is not required for every run.

## Notes

- MusicXML is the arrangement master format because it preserves score structure and part semantics better than MIDI.
- Percussion should be encoded as a real percussion part in MusicXML, not just as fake pitched notes.
- This skill is deterministic and heuristic in v1. It is not a model-based orchestrator.
