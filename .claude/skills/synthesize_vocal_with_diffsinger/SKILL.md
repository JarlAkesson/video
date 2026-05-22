# Skill 3: `synthesize_vocal_with_diffsinger`

## Purpose

Convert `vocal_events.json` into the input format expected by the chosen DiffSinger checkpoint/fork, then call DiffSinger inference to produce `rough_vocal.wav`.

This skill combines backend-specific input generation and rendering.

## Inputs

```text
vocal_events.json
```

Config:

```json
{
  "backend": "diffsinger",
  "model_path": "models/diffsinger/singer_a",
  "language": "English",
  "output": "rough_vocal.wav",
  "debug_output": "diffsinger_input.json"
}
```

## Tools

### Phonemizer / G2P

Use language-specific tools to convert lyrics/syllables to phonemes.

For English, possible tools:

- `g2p-en`
- `phonemizer`
- `pronouncing`
- fallback LLM correction for sung pronunciation

### DiffSinger

Use a DiffSinger inference script/checkpoint. DiffSinger is score-conditioned; practical inference inputs usually include text/phoneme sequence, note sequence, note durations, and slur flags.

The exact schema is fork/checkpoint-specific. This skill should hide that backend messiness.

## Internal conversion

From backend-independent events:

```json
{
  "pitch": "C4",
  "duration_beats": 1.0,
  "lyric": "Twin",
  "is_slur": false
}
```

To DiffSinger-style input:

```json
{
  "text": "twinkle twinkle little star",
  "ph_seq": "t w ih n k ax l t w ih n k ax l l ih t ax l s t aa r",
  "note_seq": "C4 C4 D4 D4 E4 E4 G4",
  "note_dur_seq": "0.50 0.50 0.50 0.50 0.50 0.50 1.00",
  "is_slur_seq": "0 1 0 1 0 1 0",
  "input_type": "phoneme"
}
```

Duration conversion:

```text
duration_seconds = duration_beats * 60 / tempo_bpm
```

## Outputs

```text
rough_vocal.wav
diffsinger_input.json
synthesis_log.json
```

## Why this output is useful

`rough_vocal.wav` is the first actual sung audio.

`diffsinger_input.json` is required for debugging:

- pronunciation problems → inspect phonemes
- rhythm problems → inspect durations
- melody problems → inspect notes
- bad held syllables → inspect slur flags

## Suggested CLI

```bash
./bin/synthesize_vocal_with_diffsinger vocal_events.json \
  --model models/diffsinger/singer_a \
  --language English \
  --out rough_vocal.wav \
  --debug-out diffsinger_input.json \
  --log synthesis_log.json
```

## Implementation notes

The first implementation can support one DiffSinger fork/checkpoint. Later, add adapter classes:

```text
DiffSingerAdapterBase
├── MoonInTheRiverAdapter
├── OpenVPIAdapter
└── CustomCheckpointAdapter
```

Each adapter should implement:

```python
build_input(vocal_events) -> backend_input
run_inference(backend_input, model_path, output_wav) -> synthesis_log
```

## Failure modes

Fail if:

- model path is missing
- phonemizer cannot process the language
- note and duration sequence lengths do not match
- DiffSinger inference exits nonzero
- output WAV is not produced

Warn if:

- unknown words required fallback phonemization
- phoneme count and note count required aggressive slur insertion
- output is clipped or silent
