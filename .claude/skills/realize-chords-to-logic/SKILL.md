---
name: realize-chords-to-logic
description: Use when a song's chord symbols should get into a Logic Pro project's global Chord Track without clicking chords in by hand. Realizes the chord symbols as sustained block chords on a second staff in MuseScore, exports a MIDI file, imports it with Logic's File > Import > MIDI File, then drags the chord region up into the Chord Track so Logic copies the chord information. Replaces the click-per-chord route of harmony2logic.
allowed-tools: Read Bash Grep Glob
argument-hint: [lead-sheet .mscz|.musicxml] [logic session already open]
effort: medium
---

# Realize chords in MuseScore -> import MIDI -> drag into the Chord Track

Logic reads chord information out of a MIDI region when you drop that region on
the Chord Track. So instead of placing chords one by one (fragile, see
`harmony2logic`), give Logic a MIDI track that *plays* the chords, import it, and
let Logic do the placement. Every chord lands exactly on its beat because it is
a real note event.

Worked example: SMOM book 5, songs 1, 2 and 3 (`MaiSTRO - Claude/Alice Tegnér Melodies/SMOM_5/`).

## Step 1 - realize the chords (MuseScore side)

```bash
/usr/bin/python3 scripts/realize_chords.py "<lead sheet>.mscz"   # default outdir = next to source
/usr/bin/python3 scripts/check_realization.py "<lead sheet>.mscz" "<stem>_chords.mscz"
```

`/usr/bin/python3` because it has music21; the default `python3` does not.
The lead sheet must be a **single-part** score with chord symbols (the `.mscz`
is the authority, not the older `.musicxml`). Outputs, never overwriting
existing files unless `--force`:

- `<stem>_chords.mscz` - two staves, chord symbols on both
- `<stem>.mid` - two MIDI tracks; the chord track is the one you drag later

**The convention (the user's own, reproduced exactly on all 19 chords of SMOM 5
song 1 and checked against the bar/offset/duration of each block):**

| Item | Rule |
|---|---|
| Top staff | melody, part name "Grand Piano" (piano sound) |
| Bottom staff | chords, part name "Melody" (Voice Oohs, program 53) - the names look swapped, but that is how the user's song 1 is; copy it, don't "fix" it, unless asked |
| Voicing | bass = bass note (slash bass) or root, **octave 2**; upper = every chord pitch class in **octave 4** (C4-B4), sorted ascending. Eb -> Eb2 / Eb4 G4 Bb4; Fm -> F2 / C4 F4 Ab4; G/B -> B2 / D4 G4 B4 |
| Rhythm | ONE sustained block per chord, from its symbol to the next symbol or the end of the bar. No re-strike, no arpeggio |
| No symbol in a bar | whole-bar rest (a pickup bar stays a rest) |
| Meter | taken from the source (3/4 -> dotted-half blocks) |

Do not write to the song's existing `_v1.mscz`; the user's own edits to it may
be sitting unsaved in MuseScore's autosave. Tell the user the new file names.

## Step 2 - import the MIDI into the open Logic session

If Logic has **no window** (System Events reports 0 windows, "Open Main Window"
does nothing) no project is open. Activating Logic can launch it into the
*Startup* dialog. Then: OK on the default "Create a new empty project", OK on the
"previously selected audio interface is not available" notice, and **Cancel** the
*Create New Track* sheet - that returns to *Choose a Project*, where "My
Templates" holds `MaiSTRO-Template1` / `MaiSTRO-Template2` (session players +
empty "Melody" tracks). Song 3 used Template2 (the preselected one) - say which
template you picked. Template2 opens at 80 BPM; importing tempo sets 120.

```bash
scripts/logic_import.py import-midi "/abs/path/<stem>.mid" --tempo import
```

(Run with `harmony2logic/venv/bin/python` if the drag helper is needed; the
import itself only needs `osascript`.) What it does, and what to do by hand if
it fails:

1. Restore/raise Logic - **the window is usually minimized or hidden behind
   the editor**; a screenshot of "Logic" can silently show VS Code instead.
2. Click *Go to Beginning* - the import lands at the playhead, so it must be bar 1.
3. Menu **File > Import > MIDI File...** (never place the notes by hand).
4. In the open panel: Cmd+Shift+G, type the absolute path, Return, Return.
5. Dialog **"Also import tempo information?"** - `Import Tempo` also brings the
   song's **time signature** (4/4 -> 3/4 happened this way) and replaces the
   session tempo in the MIDI's range; `No` keeps the session as it is. The user
   first said no, then said import it: default is `import`, but if unsure of
   the intent at the moment of the dialog, it is one word to ask.

Result: two new tracks with a region each ("Grand Piano" and "Melody"), the
meter/tempo lanes updated. Confirm with a screenshot.

## Step 3 - drag the chord track up into the Chord Track

**Select only the chord region first.** After an import both new regions are
selected ("Region: 2 selected" in the inspector). Dragging two regions shows
the tooltip *Create Multiple Chord Groups* and the drop does nothing (seen on
song 3; the user diagnosed it). A plain click on the region does not change the
selection: click empty track space first, then the chord region, and confirm the
inspector says `Region: Melody`.

```bash
scripts/logic_import.py solo <region_x> <region_y> <empty_x> <empty_y>
```

If the new regions sit at the bottom edge, scroll the track list first (scroll
wheel over the track area) so the region body is fully on screen.

Take a screenshot with `scripts/logic_import.py shot` and read positions off the
1600-px view; multiply by the printed factor (0.945 on this 1512x982-pt screen)
to get **screen points**. Then drag the *chord* region (the "Melody" region,
Voice track) straight up onto the **Chord** row of the global tracks:

```bash
scripts/logic_import.py drag <x> <region_y> <x> <chord_row_y>
```

- Grab the region body a little right of its left edge, and keep **x identical**
  at start and end so the region does not slide in time.
- The region stays on its track; Logic copies the chord information into the
  Chord Track. The lane fills with chord events across the region.
- The chord lane may not be empty. The user cleared old chords first (Undo
  History showed a `Delete Global Chords` they did themselves). If old chords
  are present, ask before deleting anything; when deleting, use Edit > Delete
  from the menu on a real selection, never the Delete key (with no valid
  selection it deletes the selected *track*).

## Step 4 - verify, then report

Zoom in (Cmd+Right x3 with Logic frontmost) until the ruler shows every bar and
read the Chord lane labels against the lead sheet: SMOM 5 song 2 read
`G | G | C | D | Am | D | Am | D | C | G | D | G | D/F# | G | D | G`, one per bar.
Edit > Undo History... lists exactly what has been done to the session.

Report what is in the session, and that **nothing is saved** (the project is
usually an unsaved "Untitled").

## Pitfalls seen

- `System Events` needs Automation permission for the calling app (reads work,
  writes silently do nothing until granted).
- The process is `Logic Pro`, not `Logic Pro X`.
- Something else (the user) may act in Logic while you work; when an unexpected
  Undo History entry appears, do not undo it.
- Drag the block-chord track ("Melody" region), not the piano melody track.
  (Dragging the melody region was not tried; it holds single notes, not chords.)

## Verified

Song 3 (SMOM 5, 4/4, 8 bars) was done end to end with this skill: chord lane read
`C | G | C | G | C | Am | Dm | G, C@beat3`, matching the lead sheet.

Realization script: reproduces the user's hand-made song-1 chord staff exactly;
song 2 passes `check_realization.py`. Logic: import panel + tempo dialog + drag
were each executed live on song 2; `logic_import.py import-midi` wraps those
same calls but has not been re-run end to end (it would have duplicated tracks
in the user's session).
