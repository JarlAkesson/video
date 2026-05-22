# Portability requirements (lock)

Generated: 2026-05-22

This repository currently has **no** local Python virtual environment at `.venv/`.
The wrapper entrypoints under `bin/` prefer `.venv/bin/python` if present, otherwise they fall back to `python3` (which may not have the required packages).

## Python runtimes

- System Python: `/home/moeen/anaconda3/bin/python3` (Python `3.13.5`, pip `25.1`)
- Conda: `conda 25.5.1`
- DiffSinger env (`conda run -n diffsinger python`): Python `3.11.15`

## Python libraries used by repo scripts

Detected by scanning `scripts/*.py` imports.

- `numpy==2.3.4` (installed)
- `pillow==11.1.0` (installed; imported as `PIL`)
- `music21` (missing in system Python; required by `scripts/analyze_music.py`, `scripts/plan_and_align_vocals.py`, etc.)

## Python libraries mentioned in skill docs (optional / future)

These are referenced in `.claude/skills/*/SKILL.md` but are not necessarily imported by current repo scripts.

- `soundfile==0.13.1` (installed)
- `librosa` (missing in system Python)
- `pydub` (missing in system Python)
- `g2p-en` (not checked)
- `phonemizer` (not checked)
- `pronouncing` (not checked)

## External command-line tools (used by skills/scripts)

- `Audiveris 5.10.2` (Commit `1b7cf44088c68f4168801822a613751d1bb1b584`, installed at `/opt/audiveris/bin/Audiveris`)
- Java: OpenJDK `21.0.10` (`openjdk-21-jre(-headless)` package version `21.0.10+7-1~25.10`)
- `musescore3` package version `3.2.3+dfsg2-19`
- `ffmpeg` package version `7:7.1.1-1ubuntu4.2`
- `fluidsynth` package version `2.4.7+dfsg-2`
- `sox` package version `14.4.2+git20190427-5build1`
- `tesseract-ocr` package version `5.5.0-1`
- `xvfb-run` (from `xvfb` package version `2:21.1.18-1ubuntu1.1`)
- Download helpers (used as fallbacks when present): `aria2c 1.37.0`, `curl 8.12.1`, `wget 1.25.0`

## External source checkouts

- DiffSinger: `third_party/DiffSinger` at commit `ebc3805f941a14490a8e8817d0a4553fb94c7945` (remote `https://github.com/openvpi/DiffSinger.git`)

## Conda environment lockfiles

- `requirements/conda-diffsinger.yml` is a `conda env export -n diffsinger --no-builds` snapshot for portability.

## Recreate (suggested)

- Create a repo-local venv and install Python deps:
  - `python3 -m venv .venv`
  - `.venv/bin/python -m pip install -U pip`
  - `.venv/bin/python -m pip install -r requirements/requirements-python.txt`
- Recreate the DiffSinger conda env:
  - `conda env create -f requirements/conda-diffsinger.yml`
