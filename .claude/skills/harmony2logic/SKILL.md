---
name: harmony2logic
description: Use when chord/harmony data from a song's harmonic arrangement (MusicXML, MuseScore project, or MIDI) needs to be entered into the Chord Track (Global Tracks) of a Logic Pro project. Reads chord symbols from the arrangement source, then drives Logic Pro's UI via computer-use to create matching chord events.
allowed-tools: Read Bash Grep Glob
argument-hint: [harmonic-arrangement-file] [logic-project-file]
effort: medium
---

# Harmony to Logic Chord Track

Take the chord/harmony content from a song's harmonic arrangement and enter it into the
Chord Track under Global Tracks in a Logic Pro (`.logicx`) project.

This skill has two phases: **extract** the harmony from the arrangement source (read-only,
file-based), then **enter** it into Logic Pro (UI automation via computer-use, since the
Chord Track lives inside the binary/package project format and isn't safely hand-edited).

## Scope

Use this skill when:

- the user has a "harmonic arrangement" of a song (typically authored in MuseScore, exported
  as `.musicxml`/`.mxl` and/or `.mid`) and a separate Logic Pro project for the same song
- the request is to put that harmony into the Logic project's **Chord Track** (the global
  track that drives Session Players / chord-following instruments), not into a regular MIDI
  track

Do not use this for adding melodic/performance MIDI — only chord-symbol data.

## Phase 1: Locate and extract the harmony

1. Find the harmonic arrangement source for the song. In this repo's convention, look under
   directories like `Harmonic Arrangements/`, `Harmonic Arrangements xml/`, or
   `Harmonic Arrangements midi/`, matching the song name (e.g. `003_Lilla_snigel`).
2. Prefer the `.musicxml` export — chord symbols are embedded as `<harmony>` elements:
   ```bash
   grep -n "harmony\|<root-step>\|<kind\|<offset>" "path/to/song.musicxml"
   ```
3. For each `<harmony>` block, record:
   - the **measure number** it appears in (`<measure number="N">`)
   - `<root-step>` (+ `<root-alter>` if present) for the chord root
   - `<kind>` (e.g. `major`, `minor`, `dominant` — dominant with `text="7"` means a 7 chord)
   - any `<degree>` alterations (e.g. for sus, add9, etc.) if present
   - the `<offset>` within the measure, if present (default = start of measure)
4. Check the score's `<time>` (beats/beat-type) and confirm it matches the Logic project's
   time signature (visible in Logic's transport bar). If they match, MusicXML measure numbers
   map 1:1 to Logic bar numbers. If they don't match, convert beats accordingly before
   proceeding — do not assume alignment.
5. Reduce the extracted harmony list to **chord-change points only**: drop repeated entries
   where the chord at measure N is identical to the still-active chord from an earlier
   measure. The Chord Track sustains a chord until the next event, so only changes matter.
6. Present the resulting chord-change list (bar -> chord) to the user before entering it,
   unless they've already described the expected progression and just want it placed.

## Phase 2: Enter the chords into Logic Pro's Chord Track

This requires controlling the Logic Pro app directly — the Chord Track is not a flat file
you can script-edit safely.

1. Request computer-use access to **Logic Pro** via `request_access`, explaining the task.
2. Open the target `.logicx` project (`open_application` with "Logic Pro"; if it's not the
   frontmost project, open the file from Finder/recents first).
3. Make the Chord Track visible if it isn't already:
   `Track menu -> Global Tracks -> Show Chord Track` (or press `G` for all global tracks).
4. For the **first** chord-change point, right-click on the Chord Track lane at that bar and
   choose **Create Chord**. Logic opens a chord editor popup with a text field — it defaults
   to detecting the nearest chord; verify/overwrite as needed and press Return.
5. For each **subsequent** chord-change point, right-click the Chord Track lane at the target
   bar and choose **Create Chord** again (the right-click menu offers "Create Chord" only when
   no chord already starts exactly there — if one does, use **Edit Chord...** instead). Type
   the chord symbol (e.g. `G7`, `Cmaj7`, `Dm`) into the Chord field and press Return.
   - The chord text field accepts standard chord shorthand (root + quality + extensions),
     parsed live into Root Note / quality buttons (Maj/Min/Sus2/.../7/9/etc.) shown below the
     field — use this to sanity-check what was actually entered before committing.
   - Click away from the popup (e.g. an empty area of the track area) to fully dismiss it
     before the next right-click; `Escape` alone may leave it open.
6. Approximate bar->x pixel mapping on screen: read two ruler tick labels (e.g. bar 1 and bar
   5) from a screenshot, compute `px_per_bar = (x5 - x1) / 4`, then target
   `x1 + (bar - 1) * px_per_bar` for any other bar. Re-derive this after any zoom/scroll.
7. After all chord events are placed, take a screenshot and zoom into the Chord Track lane to
   visually confirm the sequence of chord labels matches the extracted list.
8. Save the project (`Cmd+S`).

## Validation

- Re-screenshot and zoom on the Chord Track after saving; confirm no unsaved-changes dot
  remains in the title bar.
- Confirm the number and order of chord symbols in the Chord Track match the chord-change
  list from Phase 1 exactly.

## Notes / gotchas

- A brand-new Chord Track starts with a single default "C" chord spanning the whole
  timeline — the first real chord-change point typically just overwrites/confirms this
  rather than needing a separate insert.
- Logic's "Create Chord" only appears in the context menu when there isn't already a chord
  starting at that exact bar; if one exists, use "Edit Chord..." to change it instead of
  trying to create a duplicate.
- Don't enter redundant chord-change events for bars where the harmony hasn't actually
  changed — it's visually noisier and unnecessary, since the Chord Track sustains the prior
  chord automatically.
