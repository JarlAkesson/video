---
name: xml2midi
description: Use when a MusicXML score needs to be exported to MIDI for audio rendering or playback. Prefers MuseScore CLI; reports the blocker and any viable open-source fallback if unavailable.
allowed-tools: Read Bash Grep Glob Write
argument-hint: [musicxml-file-or-directory]
effort: medium
---

# MusicXML to MIDI

Convert symbolic score files into MIDI.

MuseScore is the required first-choice tool for this skill.

## Scope

Use this skill when the input is:

- a `.musicxml` file
- an `.mxl` file
- a directory containing MusicXML scores

## Required tool

- **MuseScore CLI**

Prefer MuseScore because it is the most direct open-source path from MusicXML to a usable MIDI export.

Do not silently switch to another converter unless the user explicitly wants a fallback.

Default target profile: **playback-first**.

## First step: prerequisite check

Always begin by resolving a MuseScore executable.

Typical checks:

```bash
command -v musescore
command -v mscore
command -v musescore4
command -v musescore3
```

Use the first working executable you find.

If MuseScore is missing:

- stop before attempting conversion
- tell the user that no MuseScore executable was found
- ask whether they want help installing it
- only continue after the tool is available

## User-level conversion options

Before conversion, determine whether the user wants defaults or a custom instrument choice.

If the user explicitly says to use defaults, proceed without asking further.

Otherwise, ask only about instrument assignment.

If the MusicXML already contains an instrument assignment, present it briefly and ask whether to keep it or replace it.

Reasonable defaults for this skill:

- preserve imported instrument assignment
- export directly with MuseScore
- trust MuseScore's playback interpretation unless the user says otherwise

## Input

The input path is provided as `$ARGUMENTS`.

If no argument is given:

- look first in `assets/_build/xml/`
- then look in `assets/xml/`
- otherwise search the current working directory for `.musicxml` and `.mxl`

## Output

Write results under:

```text
assets/_build/midi/
```

Examples:

- `assets/_build/xml/foo.musicxml` -> `assets/_build/midi/foo.mid`
- `scores/bar.mxl` -> `assets/_build/midi/bar.mid`

## Workflow

1. Resolve the input file set.
2. Resolve a MuseScore executable.
3. Resolve whether to use defaults or user-specified conversion options.
4. On headless Linux, prefer an isolated non-GUI run:
   - set `QT_QPA_PLATFORM=offscreen`
   - set temporary `HOME` and `XDG_CONFIG_HOME`
   - use `--no-webview`
   - use `-c <config-dir>` to isolate MuseScore settings for the run
5. Export each score to MIDI with MuseScore.
6. Verify that each `.mid` file exists and is non-empty.
7. Check that each produced MIDI file is structurally proper.
8. Report any notation features that may affect playback interpretation:
   - repeats not unfolded as expected
   - tempo markings
   - dynamics that may not map strongly into MIDI
   - instrument assignments

## Headless Linux notes

On Linux in a non-interactive environment, MuseScore may fail unless run with an offscreen Qt backend and isolated config paths.

A known working pattern is:

```bash
env HOME=/tmp/musescore-home XDG_CONFIG_HOME=/tmp/musescore-home QT_QPA_PLATFORM=offscreen \
musescore3 --no-webview -c /tmp/musescore-cfg \
-o /abs/path/output.mid \
/abs/path/input.mxl
```

If a plain `musescore3 -o ...` invocation hangs or fails because of display/plugin issues, retry with this pattern before concluding conversion is broken.

## Validation

Minimum validation:

- confirm the MIDI file exists
- report file size
- if a MIDI inspection tool is available, report track count or duration
- if possible, confirm the MIDI header is valid (`MThd`)

## MIDI integrity check

Do not stop at file existence.

At the end, check whether the produced MIDI file is actually proper MIDI data.

At minimum:

- confirm the file starts with the standard MIDI header `MThd`
- report format type if available
- report track count if available
- report timing division if available

If the file exists but fails these checks, do not describe the conversion as successful.

Do not describe the MIDI as "audio". It is event data, not rendered sound.

## Failure handling

If MuseScore is unavailable:

- say so plainly
- state that no usable MuseScore executable was found
- ask the user whether they want help installing it
- do not proceed with conversion until the tool is available

If conversion fails on some files:

- keep successful outputs
- list failed inputs separately

If MuseScore fails in a headless environment:

- do not assume the score is bad
- report the environment failure separately
- retry with offscreen Qt and isolated config paths before giving up

## Installation help

If the user wants installation help, first identify the platform.

### Linux

Prefer one of:

- the system package if it is reasonably current
- the official package or repository if needed
- Flatpak if the user already uses Flatpak

After installation, re-check with:

```bash
command -v musescore || command -v mscore || command -v musescore4 || command -v musescore3
```

### Windows

Prefer the official MuseScore installer.

Help the user:

- download the installer
- install MuseScore
- ensure the executable is callable, or explain that they may need to run it by full path

## Final response

Report:

- input MusicXML path(s)
- output MIDI path(s)
- tool used
- whether defaults or custom conversion options were used
- whether conversion succeeded
- any playback-relevant caveats noticed during export
