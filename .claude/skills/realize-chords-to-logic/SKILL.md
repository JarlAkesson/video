---
name: realize-chords-to-logic
description: Use when a song's chord symbols should get into a Logic Pro project - the melody and block-chord MIDI tracks AND the global Chord Track. Realizes the chord symbols as sustained block chords on a second staff in MuseScore, exports MIDI, imports it with Logic's File > Import > MIDI File, lays out sections (lead-in, repeats, gaps), and enters every Chord Track event exactly on its beat by placing the playhead and clicking the Chord track's "+" button. Also covers fixing a Chord Track whose chords are shifted off the beat.
allowed-tools: Read Bash Grep Glob
argument-hint: [lead-sheet .mscz|.musicxml] [logic session already open]
effort: medium
---

# Realize chords in MuseScore -> import MIDI -> exact Chord Track

**Get the Chord Track right on the first try.** Fixing a misplaced Chord Track means
clearing it and re-entering every chord, which costs far more than entering it correctly
once. So the Chord Track is entered with the one method verified to be tick-exact
(Step 4). Do **not** fill it by dropping a MIDI region onto the Chord lane: that
analysis places chords 20-40 ticks *after* the beat (measured on SMOM 5 song 4: bar 5
chord at `5 1 1 20`, bar 6 at `6 1 1 38`), and setting Snap to Beat did not change that.
The user saw every chord shifted slightly right and asked for a fix.

Worked examples: SMOM book 5, songs 1-4 (`MaiSTRO - Claude/Alice Tegnér Melodies/SMOM_5/`).

Scripts (`scripts/`; music21 ones with `/usr/bin/python3`, UI ones with
`../harmony2logic/venv/bin/python`):

| Script | Does |
|---|---|
| `realize_chords.py` / `check_realization.py` | lead sheet -> two-staff score + `.mid`; verify |
| `chord_spec.py` | the exact Chord Track event list for a layout (`bar:name`, `bar.beat:name`) |
| `logic_import.py` | `front`, `shot`, `import-midi`, `goto BAR`, `move-to-playhead`, `solo`, `drag` |
| `chord_at_playhead.py` | enters chord events at the playhead, one per spec |
| `make_leadin.py` | tonic-only MIDI (only if a tonic *MIDI* bar is wanted; not needed for the Chord Track) |

## Step 1 - realize the chords (MuseScore side)

```bash
/usr/bin/python3 scripts/realize_chords.py "<lead sheet>.mscz"   # default outdir = next to source
/usr/bin/python3 scripts/check_realization.py "<lead sheet>.mscz" "<stem>_chords.mscz"
```

The lead sheet must be a **single-part** score with chord symbols (the `.mscz` is the
authority, not the older `.musicxml`). Outputs, never overwriting unless `--force`:
`<stem>_chords.mscz` (two staves, chord symbols on both) and `<stem>.mid` (two tracks).

**The convention (the user's own, reproduced exactly on all 19 chords of SMOM 5 song 1):**

| Item | Rule |
|---|---|
| Top staff | melody, part name "Grand Piano" (piano sound) |
| Bottom staff | chords, part name "Melody" (Voice Oohs, program 53) - names look swapped; that is how the user's song 1 is, don't "fix" it unless asked |
| Voicing | bass = bass note (slash bass) or root, **octave 2**; upper = every chord pitch class in **octave 4** (C4-B4), ascending. Eb -> Eb2 / Eb4 G4 Bb4; G/B -> B2 / D4 G4 B4 |
| Rhythm | ONE sustained block per chord, symbol to next symbol or bar end |
| No symbol in a bar | whole-bar rest (a pickup bar stays a rest) |

Do not write to the song's existing `_v1.mscz` (the user's edits may sit unsaved in the
autosave). Tell the user the new file names.

## Step 2 - plan the layout before touching Logic

Write the bar plan out and get the chord list from the script, **before any clicking**:

```bash
/usr/bin/python3 scripts/chord_spec.py "<lead sheet>.mscz" --starts 5,15,25
# 1:Dm 5:Dm 6:F 8:A 9:C 10:Dm 11:A 12:Dm 15:Dm 16:F ... 32:Dm
```

- First downbeat of the song at **bar 5** (4/4, 3/4, 6/8) or **bar 9** (2/4); tonic before.
- Repeats as the user asks, e.g. song 4: section at 5, 2 bars tonic, section at 15,
  2 bars tonic, section at 25, 4 bars tonic at the end -> `--starts 5,15,25`.
- The script emits bar 1 tonic, every chord change, every section's first downbeat, and
  the tonic after each section (gaps, ending). The Chord Track sustains, so no event is
  needed while the chord stays the same.
- Mid-bar changes come out as `bar.beat` (song 3: `12.3:C`).
- Sanity-check the printed key/tonic against the first/last chord symbol.

## Step 3 - MIDI tracks in Logic

**Template.** If Logic has no window (0 windows; "Open Main Window" does nothing) no project
is open: activate Logic -> Startup dialog -> OK, OK on the audio-interface notice, **Cancel**
the *Create New Track* sheet -> *Choose a Project* -> My Templates. Pick the template whose
meter equals the song's starting time signature: `MaiSTRO_2:4_Template`,
`MaiSTRO_3:4_Template`, `MaiSTRO_4:4_Template`, `MaiSTRO_6:8_Template`
(`~/Music/Audio Music Apps/Project Templates/`). Templates open at 80 BPM.

**Import** (the real `<stem>.mid`, never only a helper):

```bash
/usr/bin/python3 scripts/logic_import.py import-midi "/abs/path/<stem>.mid" --tempo import
```

Raises/restores Logic (it is often minimized or behind the editor), File > Import > MIDI
File..., Cmd+Shift+G path, Return x2, then **Import Tempo** (brings 120 BPM and the song's
meter). Result: two new tracks, "Grand Piano" and "Melody", **always at bar 1** - Logic
ignores the playhead for MIDI imports.

**Move to the first downbeat** - both regions are still selected after the import:

```bash
/usr/bin/python3 scripts/logic_import.py goto 5
/usr/bin/python3 scripts/logic_import.py move-to-playhead      # Edit > Move > To Playhead
```

**Repeats**: rubber-band select both regions (drag across empty space around them), Edit >
Copy; `goto 15`, click the header row of the upper of the two MIDI tracks, Edit > Paste;
repeat for each start. Screenshot: every region must start on its bar line.

## Step 4 - the Chord Track, exact on the first try

The only method verified tick-exact: **put the playhead on the beat, click the "+" in the
Chord global-track header, type the name, Return.** The chord is created at the playhead
(read back as `B 1 1 001`).

1. **Snap = Bar** (toolbar "Snap:" popup; Logic's default "Smart" is zoom-dependent).
   Hide the Library panel (View > Library) so the toolbar shows Snap.
2. The Chord lane must be empty or hold only chords you are about to keep. If it has old
   chords, clear it first (see "Clearing the Chord Track").
3. Screenshot (`logic_import.py shot`) and read two points off the 1600-px view, times the
   printed factor (0.945 here) -> screen points:
   - `--plus`: the round **"+" at the right end of the "Chord" header** (e.g. view (581,414)
     with the Inspector shown -> (549, 391) pt). Verify on the screenshot that it is the
     Chord row's "+", not Signature's or Marker's.
   - `--empty`: a spot of **empty track area** (no region, no header), used to dismiss the
     chord popover.
4. Test **one** chord and read it back before the batch:

   ```bash
   ../harmony2logic/venv/bin/python scripts/chord_at_playhead.py --plus 549 391 --empty 1228 661 5:Dm
   ```

   Check: the popover closed, the lane shows `Dm` starting on the bar-5 line. Then the
   rest in one call, in the order `chord_spec.py` printed:

   ```bash
   ../harmony2logic/venv/bin/python scripts/chord_at_playhead.py --plus 549 391 --empty 1228 661 1:Dm 6:F 8:A ...
   ```

5. **Check the popover really closed after the last chord.** Once a popover was left open
   when the dismiss click landed on the popover itself, so pick `--empty` far away from
   where the popover appears (it opens next to the playhead, over the top of the tracks).

Why not create chords by right-clicking the lane: that places a chord at the *click* x, so
it is only as good as the pixel calibration and Snap. The playhead route has no pixel error.

## Step 5 - verify the positions, then report

- **Exact position**: click a chord in the lane, Navigate > Go To > Selection Start, and
  read the transport: it must be `B 1 1 001` (a late chord reads e.g. `6 1 1 038`). Check
  the first chord, one mid-bar change if any, and one chord per section.
- **Names**: zoom so every bar is visible and read the lane against `chord_spec.py`.
- Edit > Undo History... shows every action; report what is in the session and that
  **nothing is saved** (usually an unsaved "Untitled").

## Fixing a Chord Track that is shifted off the beat

Symptom: every chord sits a little right of its bar line (dropped-region analysis).
Nothing in the MIDI is wrong (Event List shows notes at `5 1 1 1`); the Chord Track events
are. Fix = clear the lane, then Step 4.

### Clearing the Chord Track (without losing regions)

1. **Deselect all regions first**: click empty track area. `Edit > Delete` deletes
   *everything selected* - on song 4 it removed the selected section-1 "Melody" region
   together with the chords (recovered through Undo History).
2. Right-click in the Chord lane -> **Select All Chords** (the menu flips left near the right
   screen edge; read its position from a screenshot).
3. **Edit > Delete** from the menu bar (never the Delete key: with no valid selection it
   deletes the selected *track*).
4. Screenshot: lane empty (only the grey default chord), every region still there.

If something extra got deleted: Edit > Undo History..., select the last entry *before* the
mistake, **Undo**; if that also rolled back a user action, select it and **Redo** only that
step. Never use Edit > Undo blindly - check the item's name (it once undid the user's own
"Load Patch").

## Pitfalls seen

- `System Events` needs Automation permission (reads work, writes silently do nothing).
- The process is `Logic Pro`, not `Logic Pro X`.
- After an import both regions are selected: a drag of both onto the Chord lane only shows
  *Create Multiple Chord Groups* and drops nothing; a click on a region does not reduce the
  selection - click empty space first.
- Grabbing a region near its bottom edge moved it to a new track instead of the lane.
- The user edits the session while you work (deleted regions, loaded patches) - re-screenshot
  before acting on old coordinates; never undo an entry you did not make.
- Hiding the Library/Inspector moves every x coordinate - re-read positions after any
  layout change.

## Verified

- Song 4 (SMOM 5, 3/4, D minor, 8 bars, sections at 5/15/25): Chord Track re-entered with
  the playhead + "+" method; `5 1 1 1` and `12 1 1 1` read back exactly, lane boundaries sit
  on the bar lines at bars 10/11. (Initially filled by region drops: 20-38 ticks late.)
- Song 3 (4/4, mid-bar `C` at 12.3) and song 2 (3/4) went through Steps 1-3; their Chord
  Tracks were filled by region drops, so they have the same late-chord offset unless redone.
- `chord_spec.py` output checked for song 4 (5,15,25 and 5,13) and song 3 (5).
- Realization reproduces the user's song-1 chord staff exactly; song 2 passes the check.
