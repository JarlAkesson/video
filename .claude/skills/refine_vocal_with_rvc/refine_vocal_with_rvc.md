# Skill 4: `refine_vocal_with_rvc`

## Purpose

Optionally improve the DiffSinger vocal by running it through an RVC/SVC voice conversion model.

This is a refinement step, not the core singing step.

## Inputs

```text
rough_vocal.wav
```

Config:

```json
{
  "rvc_model": "models/rvc/singer_b.pth",
  "rvc_index": "models/rvc/singer_b.index",
  "transpose": 0,
  "output": "refined_vocal.wav"
}
```

## Tools

Use an RVC CLI or Python wrapper.

RVC converts existing vocal audio into a target voice/timbre. It does not create singing from symbolic notes. That is why this skill comes after DiffSinger.

## Responsibilities

1. Validate input WAV.
2. Run RVC/SVC inference.
3. Preserve timing and length as much as possible.
4. Detect clipping/silence/artifacts.
5. Write `refined_vocal.wav` and `rvc_log.json`.

## Outputs

```text
refined_vocal.wav
rvc_log.json
```

Example log:

```json
{
  "input": "rough_vocal.wav",
  "output": "refined_vocal.wav",
  "model": "models/rvc/singer_b.pth",
  "transpose": 0,
  "duration_seconds": 23.42,
  "warnings": []
}
```

## Why this output is useful

DiffSinger solves structure:

```text
notes + lyrics → sung vocal
```

RVC solves timbre/texture:

```text
rough synthetic vocal → more natural/pleasant vocal
```

Keep this step optional because it can sometimes:

- blur consonants
- add artifacts
- reduce lyric intelligibility
- over-color the singer identity

The pipeline should always preserve both:

```text
rough_vocal.wav
refined_vocal.wav
```

for A/B comparison.

## Suggested CLI

```bash
refine_vocal_with_rvc rough_vocal.wav \
  --model models/rvc/singer_b.pth \
  --index models/rvc/singer_b.index \
  --transpose 0 \
  --out refined_vocal.wav \
  --log rvc_log.json
```

## Failure modes

Fail if:

- input WAV missing or silent
- RVC model missing
- inference exits nonzero
- output WAV missing

Warn if:

- output duration differs significantly from input
- output clips above -1 dBFS
- spectral/noise checks suggest severe artifacts
