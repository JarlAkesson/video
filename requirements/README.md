# Requirements

This directory contains pinned dependency snapshots for the pipeline.
There are three separate environments to set up.

---

## 1. Python virtual environment (repo scripts)

Create a local venv and install Python dependencies:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -r requirements/requirements-python.txt
```

The `bin/` wrappers automatically prefer `.venv/bin/python` when it exists.

---

## 2. DiffSinger conda environment (vocal synthesis)

The DiffSinger vocal synthesis backend runs in a separate conda environment
to isolate its dependencies from the rest of the project:

```bash
conda env create -f requirements/conda-diffsinger.yml
```

Activate it when running DiffSinger inference directly:

```bash
conda activate diffsinger
```

The `synthesize-vocal-with-diffsinger` skill handles this automatically.

---

## 3. System tools

The pipeline relies on several external command-line tools. Install them via
your system package manager (e.g. `apt` on Ubuntu/Debian):

```bash
sudo apt install openjdk-21-jre musescore3 ffmpeg fluidsynth sox tesseract-ocr xvfb
```

Audiveris (sheet music recognition) requires a separate install:

```
/opt/audiveris/bin/Audiveris   ← expected path
```

See `requirements-tools.txt` for the exact versions used on the reference machine.

---

## Files in this directory

- `requirements-python.txt` — pip packages for repo scripts
- `requirements-tools.txt` — system tool versions captured from the reference machine
- `conda-diffsinger.yml` — conda env export for DiffSinger
- `requirements.lock.md` — full portability snapshot: Python runtimes, installed versions, and what is missing
