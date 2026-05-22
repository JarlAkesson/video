---
name: sheet2xml
description: Convert sheet-music PDFs or images into MusicXML using an open-source OMR workflow. Prefer Audiveris for recognition, save outputs under assets/_build/xml/, and report recognition weaknesses that need manual cleanup.
allowed-tools: Read Bash Grep Glob Write
argument-hint: [sheet-file-or-directory]
effort: medium
---

# Sheet Music to MusicXML

Convert printed sheet music into MusicXML.

Audiveris is the required engine for this skill.

Default target profile: **playback-first**.

That means the main question is not only whether MusicXML was exported, but whether the result is likely usable for:

- MIDI generation
- audio rendering
- basic score cleanup in MuseScore

Lyrics and text OCR are secondary unless the user explicitly asks for notation/text fidelity.

## Scope

Use this skill when the input is:

- a scanned PDF of sheet music
- a photo or image of printed notation
- a directory containing such files

Do not use this skill for handwritten music unless the user explicitly wants a best-effort attempt.

## Required tools

- **Audiveris**
- **Xvfb** for headless Linux execution when no X server is available
- **Tesseract OCR support** for lyric and text recognition
- **Output format**: MusicXML (`.musicxml` or `.mxl`)
- **Manual correction stage after this skill**: MuseScore

Before doing any conversion, resolve an Audiveris executable.

## First step: prerequisite check

Always begin by checking for Audiveris.

Typical check:

```bash
command -v audiveris
```

Also check common alternate command names:

```bash
command -v Audiveris
```

If those fail, check the common Linux installer path:

```bash
test -x /opt/audiveris/bin/Audiveris
```

Use the first working executable you find.

Preferred resolution order:

1. `audiveris`
2. `Audiveris`
3. `/opt/audiveris/bin/Audiveris`

On Linux, also check:

```bash
command -v xvfb-run
command -v tesseract
```

If the environment is headless and `xvfb-run` is unavailable, do not claim the CLI path is ready.

If Audiveris is present:

- continue with the conversion workflow using the resolved executable path

If Audiveris is missing:

- stop before attempting conversion
- tell the user that no Audiveris executable was found on `$PATH` and not at `/opt/audiveris/bin/Audiveris`
- ask the user where Audiveris is installed (request a full path to the executable)
- if the user does not have it installed, then ask whether they want help installing it
- only continue after a working executable path is provided or discovered

Do not silently switch to another OMR engine.

## Input

The input path is provided as `$ARGUMENTS`.

If no argument is given:

- first look in `assets/sheets/` for likely score files
- if `assets/sheets/` does not exist or contains no matching files, then look in the current working directory
- prefer `.pdf`, `.png`, `.jpg`, `.jpeg`, `.tif`, `.tiff`

## Output

Write results under:

```text
assets/_build/xml/
```

Also write a conversion log under:

```text
assets/_build/xml/logs/
```

Use the base filename of the source score.

Examples:

- `assets/sheets/foo.pdf` -> `assets/_build/xml/foo.musicxml`
- `assets/sheets/bar.png` -> `assets/_build/xml/bar.musicxml`
- `assets/sheets/foo.pdf` -> `assets/_build/xml/logs/foo.audiveris.log`

## Workflow

1. Inspect the input type and page structure.
2. If the input is a PDF, determine whether it appears to be born-digital or scanned; do not assume recognition quality.
3. On Linux, if no usable X server is available, run Audiveris through `xvfb-run`.
4. Run Audiveris.
5. Save the full Audiveris stdout/stderr log in `assets/_build/xml/logs/`.
6. Export MusicXML into `assets/_build/xml/`.
7. Check whether the output file was actually produced.
8. Read the log and report likely weak spots:
   - polyphonic passages
   - tuplets
   - cross-staff notation
   - lyrics alignment
   - repeats, voltas, codas
   - articulations and dynamics
   - octave-shift markings
   - symbol-linking failures
   - rhythm and measure anomalies

## Log review

Do not stop at "the `.mxl` file exists".

Read the Audiveris log and summarize:

- whether export succeeded
- number of sheets processed
- number of systems found, if reported
- number of measures found, if reported
- warnings and exceptions
- suspicious messages that may affect MIDI/audio usability

For a playback-first workflow, pay particular attention to log messages involving:

- measure detection
- rhythm handling
- missing or conflicting chord links
- octave-shift symbols
- key signature / clef / time signature recognition
- repeat structure

Treat missing OCR languages as a secondary warning unless the user explicitly cares about lyrics or score text.

## Validation

Minimum validation:

- confirm the MusicXML file exists
- report file size
- if possible, inspect the header for basic score metadata
- confirm the log file exists

For playback-first validation, also state whether the run appears:

- `Verified`: exported successfully with no serious structural warnings noticed
- `Likely`: exported successfully but warnings suggest cleanup before MIDI/audio
- `Gap`: export failed, or the log suggests the score structure is unreliable

Do not claim the MusicXML is correct without saying it still needs score-level review.

## MusicXML plausibility checks

After confirming that the MusicXML file exists, inspect the content itself.

The goal is not to prove the score is correct, but to detect obvious musical or structural problems before moving on to MIDI/audio generation.

### Required checks

1. **Basic score structure**
   - confirm the file is parseable MusicXML
   - identify the number of parts
   - identify the number of measures
   - identify the initial key, time signature, and clef when present

2. **Measure-duration consistency**
   - compare each measure against the active time signature
   - flag measures that appear underfilled or overfilled
   - account for tuplets, rests, and multi-voice constructs such as `backup`

3. **Pitch-range sanity**
   - flag obviously implausible pitches for the part or local context
   - flag sudden isolated octave jumps that suggest failed recognition

4. **Voice-structure sanity**
   - report whether the score is mostly single-voice or contains multiple voices
   - flag unexpectedly messy voice splits for a simple melody
   - flag excessive `backup` usage if the score should be monophonic

5. **Playback-symbol survival**
   - check whether important playback-relevant symbols appear in the XML when expected:
     - tempo marks
     - dynamics
     - repeats/endings
     - ties/slurs
     - octave-shift markings
   - if the log reported unlinked octave-shift symbols and the XML has no usable octave-shift directions, flag this clearly

### Optional heuristic checks

- repeated-pattern consistency across similar measures
- accidental density relative to the key signature
- suspiciously fragmented rests
- unusually dense ornamentation or directions for a simple song

### Reporting

Summarize the plausibility check in plain language.

At minimum, report:

- whether the XML looks structurally coherent
- whether it looks usable for playback
- which measures or regions should be inspected first
- which issues are likely harmless versus likely to affect MIDI/audio

## Failure handling

If Audiveris is unavailable:

- say so plainly
- do not invent a fake conversion
- state that no usable Audiveris executable was found
- ask the user whether they want help installing it
- if they say yes, help them install it for their platform
- do not proceed with conversion until the tool is available

If Linux headless support is missing:

- say that `xvfb-run` is required in this environment
- ask whether the user wants help installing it
- do not present this as a score-recognition failure

If OCR support is missing:

- say that `tesseract` or its language data is missing
- explain that note recognition may still run, but text and lyric recognition will be degraded
- if the target is playback-first, mark this as non-blocking unless the log suggests broader OCR failure

## Installation help

If the user wants installation help, first identify the platform.

### Linux

Prefer one of:

- the system package if it is reasonably current
- the official `.deb` package when appropriate
- Flatpak if the user already uses Flatpak

Also install, when needed:

- `xvfb`
- `tesseract-ocr`

After installation, ask the user to confirm the executable is available, or re-check with:

```bash
command -v audiveris || test -x /opt/audiveris/bin/Audiveris
```

### Windows

Prefer the official Windows installer.

Help the user:

- download the installer
- install Audiveris
- ensure the executable is callable, or explain that they may need to run it by full path

Do not guess package-manager commands unless the environment clearly supports them.

If recognition only partially works:

- keep the partial output
- describe the failure mode briefly
- recommend cleanup in MuseScore

## Final response

Report:

- input file(s) processed
- output MusicXML path(s)
- log path(s)
- tool used
- whether the conversion succeeded
- playback-first status: `Verified`, `Likely`, or `Gap`
- major warnings found in the log
- what likely needs manual correction in MuseScore
- what the user should inspect first:
  - rhythms and measure count
  - octave-shift markings
  - repeats/endings
  - articulations/dynamics
  - lyrics/text only if they care about them

If the run stopped because Audiveris was missing, report that clearly instead of pretending the skill completed.
