# Video music pipeline (research workspace)

This repo is a scratchpad for an end-to-end music pipeline (sheet/MusicXML → arrangement → MIDI/audio → vocals → mix).

## Wrapper entrypoints (`bin/`)

`bin/` contains small bash wrappers that invoke the corresponding `scripts/*.py`.

- They prefer `.venv/bin/python` if it exists; otherwise they fall back to `python3`.
- Run them as `./bin/<name> ...`, or add `./bin` to your `PATH`.

Current wrappers:

- `bin/analyze_inputs`
- `bin/analyze_music`
- `bin/download_scores`
- `bin/mix_and_validate`
- `bin/plan_and_align_vocals`
- `bin/syllabify_lyrics`
- `bin/synthesize_vocal_with_diffsinger`

## Skills + schemas

Design docs live under `.claude/`:

- `.claude/README.md` (overall pipeline + typical flows)
- `.claude/skills/*/SKILL.md` (skill specs)
- `.claude/schemas/` (JSON schemas for intermediate artifacts)

## Portability manifests

See `requirements/` for pinned snapshots of Python deps and external tools:

- `requirements/requirements-python.txt`
- `requirements/requirements-tools.txt`
- `requirements/requirements.lock.md`

