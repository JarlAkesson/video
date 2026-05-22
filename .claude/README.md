# Music Pipeline Skills (Draft)

This folder contains *first-draft* skills/specs for an end-to-end pipeline:

1. Acquire sheet music (optional).
2. Convert sheet music → MusicXML.
3. Arrange/augment the score (still MusicXML, still editable).
4. Convert MusicXML → MIDI → rendered instrumental audio.
5. Add vocals from separate lyrics via DiffSinger (+ optional RVC polish).
6. Mix and validate the result.

These were written for Claude-style “skills”, but they also serve as design docs for building a real CLI/tooling stack in this repo.

## Typical flows

### Wrapper entrypoints (`bin/`)

This repo includes small bash wrappers under `bin/` that invoke the corresponding `scripts/*.py`.

- They prefer `.venv/bin/python` if it exists, otherwise they fall back to `python3`.
- Use them as `./bin/<name> ...`, or add `./bin` to your `PATH`.

### Instrumental-only

```bash
sheet2xml assets/sheets/foo.pdf
arrange-score assets/_build/xml/foo.musicxml --goal "gentle children's song"
xml2midi assets/_build/xml/foo.<tag>.musicxml
midi2music assets/_build/midi/foo.<tag>.mid
```

### Add vocals (from lyrics)

```bash
./bin/analyze_music assets/_build/xml/foo.<tag>.musicxml --out assets/_build/vocals/music_analysis.json
./bin/syllabify_lyrics assets/lyrics/lyrics.txt --out assets/_build/vocals/lyrics.json
./bin/plan_and_align_vocals assets/_build/vocals/music_analysis.json assets/_build/vocals/lyrics.json --cue "clear vocals, minimal melisma" --out assets/_build/vocals/vocal_events.json
./bin/synthesize_vocal_with_diffsinger assets/_build/vocals/vocal_events.json --model models/diffsinger/singer_a --out assets/_build/vocals/rough_vocal.wav --debug-out assets/_build/vocals/diffsinger_input.json
refine_vocal_with_rvc assets/_build/vocals/rough_vocal.wav --model models/rvc/singer_b.pth --index models/rvc/singer_b.index --out assets/_build/vocals/refined_vocal.wav
./bin/mix_and_validate assets/_build/xml/foo.<tag>.musicxml assets/_build/vocals/refined_vocal.wav --out assets/_build/vocals/final_song.wav --report assets/_build/vocals/mix_report.json
```

Notes:
- The command names above are *intended* CLIs; not all are necessarily implemented as executables yet.
- Outputs are generally written under `assets/_build/` to keep intermediate artifacts organized.

## Skills (by stage)

### Acquisition (optional)

- `skills/download-scores/SKILL.md`: download public-domain/allowed scores listed in a CSV into `assets/` (draft assumes web search/fetch tooling).

### Sheet → MusicXML

- `skills/sheet2xml/SKILL.md`: OMR with Audiveris (+ `xvfb-run` for headless Linux), outputs `assets/_build/xml/*.musicxml` and logs in `assets/_build/xml/logs/`.

### Arrangement (MusicXML → MusicXML)

- `skills/arrange-score/SKILL.md`: heuristic arrangement/restyle via `scripts/arrange_score.py`, outputs `assets/_build/xml/<basename>.<tag>.musicxml`.

### MusicXML → MIDI → audio

- `skills/xml2midi/SKILL.md`: export MIDI with MuseScore CLI, outputs `assets/_build/midi/*.mid`.
- `skills/midi2music/SKILL.md`: render MIDI to audio with FluidSynth + a SoundFont, outputs `assets/_build/audio/*.wav` (+ logs in `assets/_build/audio/logs/`).

### Vocals

- `skills/analyze_music/SKILL.md`: parse arranged score into `music_analysis.json` (music21 analysis only).
- `skills/syllabify_lyrics/SKILL.md`: parse `lyrics.txt` into `lyrics.json` (syllabification only).
- `skills/plan_vocals/SKILL.md`: LLM-assisted plan/alignment from `music_analysis.json` + `lyrics.json` to `vocal_events.json`.
- `skills/synthesize_vocal_with_diffsinger/SKILL.md`: build DiffSinger input and run inference → `rough_vocal.wav` (+ `diffsinger_input.json`, `synthesis_log.json`).
- `skills/refine_vocal_with_rvc/SKILL.md`: optional RVC/SVC polish → `refined_vocal.wav` (+ `rvc_log.json`).

### Mix + validation

- `skills/mix_validate/SKILL.md`: render instrumental stem, align, mix, and emit `final_song.wav` + `mix_report.json`.

## Schemas

These JSON Schemas define the repo’s intermediate artifacts. The pipeline is intended to be “schema-first”: LLM steps produce/consume structured JSON, and the Python tools validate and materialize it into MusicXML/audio.

- `schemas/analysis.schema.json`
  - Purpose: top-level “inputs summary” contract for `scripts/analyze_inputs.py` when you want one compact JSON describing what files are present and what downstream steps are feasible.
  - Typical contents: discovered input file paths (PDF/MusicXML/MIDI/lyrics), basic metadata, and warnings.
- `schemas/music_analysis.schema.json`
  - Purpose: contract for `music_analysis.json` emitted by `scripts/analyze_music.py`.
  - Used by: `plan_and_align_vocals` as the musical facts layer (tempo/meter/key/parts/phrases/melody candidates/harmony + warnings).
- `schemas/lyrics.schema.json`
  - Purpose: contract for `lyrics.json` emitted by `scripts/syllabify_lyrics.py`.
  - Typical contents: normalized lyric lines + per-line syllable breakdown + language hint + warnings (unknown words, odd punctuation).
- `schemas/vocal_events.schema.json`
  - Purpose: contract for `vocal_events.json` produced by the LLM-assisted planning step (`plan_and_align_vocals`).
  - Typical contents: a flat event list with `(measure, start_beat, duration_beats, pitch, lyric, is_slur, breath_after, …)` plus global tempo/meter/language/style and warnings.
  - Used by: DiffSinger input generation and any later re-timing / validation.
- `schemas/diffsinger_input.schema.json`
  - Purpose: contract for the backend-specific DiffSinger payload (for example `diffsinger_input.json`) generated by `scripts/synthesize_vocal_with_diffsinger.py`.
  - Typical contents: `ph_seq`, `note_seq`, `note_dur_seq`, `is_slur_seq`, plus any checkpoint/fork metadata needed to reproduce inference.
- `schemas/mix_report.schema.json`
  - Purpose: contract for `mix_report.json` emitted by `scripts/mix_and_validate.py`.
  - Typical contents: file outputs, timing/offset summary, level (peak) summary, and a list of structured warnings/suggested next actions.

## Design principle

```text
LLM plans.
Python extracts, converts, validates, and renders.
Audiveris recognizes.
MuseScore exports.
FluidSynth renders.
DiffSinger sings.
RVC optionally polishes.
Mixer assembles and validates.
```
