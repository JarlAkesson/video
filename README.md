# Children's Music Video Pipeline

This project turns sheet music into entertaining music videos for children.
It combines music arrangement, AI-generated singing, and video production.

---

## How the project is organized

This project uses two places to store files.

**This repository (GitHub)** stores text-based files: scripts, skill definitions,
lyrics as plain text, song catalogs, and documentation. Only text files belong
here — things you can open in a text editor and read directly.

**Google Drive** stores large binary files that cannot go into git: sheet music
PDFs, audio files (MP3, WAV), MIDI files, images, and video exports.
See [docs/drive](docs/drive/README.md) for the Drive folder structure.

**The rule:** if you can open it in a text editor and read it as plain text, it
goes in this repository. If it is a PDF, audio file, image, or video, it goes on Drive.

### Project layout

```
assets/          local working copies of Drive files (gitignored; sync from Drive)
bin/             shell wrappers that invoke scripts/
docs/            project documentation
requirements/    pinned Python and tool dependencies
scripts/         Python implementation of each pipeline stage
tests/           automated tests
third_party/     external tools (DiffSinger, etc.)
.claude/         Claude skills, schemas, and pipeline design docs
```

### Pipeline stages

```
Sheet music (PDF/image)
  → sheet2xml      scan with Audiveris → MusicXML
  → arrange-score  arrange/restyle     → MusicXML
  → xml2midi       export              → MIDI
  → midi2music     render              → audio (WAV)
  → [vocals]       DiffSinger + RVC    → vocal WAV
  → mix_validate   mix + validate      → final WAV
```

### Requirements

See `requirements/` for pinned snapshots of Python and tool dependencies.

---

## Working with Claude

When Claude Code is launched from the project root, the contents of `.claude/`
are automatically loaded into the session. This makes all project skills
available as slash commands (e.g. `/arrange-score`, `/synthesize-vocal-with-diffsinger`).
Always launch Claude from the project root, not from a subdirectory.

Design docs under `.claude/`:

- `.claude/README.md` — overall pipeline flows
- `.claude/skills/*/SKILL.md` — per-stage skill specs
- `.claude/schemas/` — JSON schemas for intermediate artifacts

### Skills

Each skill is one stage of the pipeline. They pass structured JSON files to each other.

**Acquiring and preparing scores**

- `/download-scores` — downloads sheet music and MIDI files for songs listed in a CSV catalog
- `/sheet2xml` — converts a sheet music PDF or image into MusicXML using Audiveris (OMR)
- `/arrange-score` — takes a MusicXML score and produces a new arranged version based on a style goal (e.g. hip-hop remix, add violin and drums)

**Generating audio from the score**

- `/xml2midi` — exports a MusicXML score to MIDI using MuseScore
- `/midi2music` — renders a MIDI file to audio (WAV) using FluidSynth and a SoundFont

**Adding vocals**

- `/analyze-music` — parses the arranged score into `music_analysis.json`: tempo, key, phrases, melody candidates
- `/syllabify-lyrics` — parses `lyrics.txt` into `lyrics.json`: lines broken into syllables
- `/plan-vocals` — takes `music_analysis.json` + `lyrics.json` and produces `vocal_events.json`, mapping each syllable to a melody note. This is the main LLM-assisted step.
- `/synthesize-vocal-with-diffsinger` — turns `vocal_events.json` into a sung `rough_vocal.wav` using the Nishiren DiffSinger v2.0 ONNX voicebank
- `/refine-vocal-with-rvc` — optional step that runs `rough_vocal.wav` through an RVC voice conversion model to improve timbre

**Mixing**

- `/mix-validate` — renders the instrumental stem, combines it with the vocal, and exports `final_song.wav` along with a `mix_report.json` flagging timing, level, and masking issues

---

## Documentation

- [docs/drive](docs/drive/README.md) — Google Drive folder structure; where to find and put binary files
- [docs/music](docs/music/README.md) — song catalog, arrangement experiments, and musical insights
