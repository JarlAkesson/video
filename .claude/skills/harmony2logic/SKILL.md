---
name: harmony2logic
description: Use when chord/harmony data from a song's harmonic arrangement (MusicXML, MuseScore project, or MIDI) needs to be entered into the Chord Track (Global Tracks) of a Logic Pro project. Reads chord symbols from the arrangement source, then drives Logic Pro's UI via scripted clicks to create, rename and delete chord events.
allowed-tools: Read Bash Grep Glob
argument-hint: [harmonic-arrangement-file] [logic-project-file]
effort: medium
---

# Harmony to Logic Chord Track

Take the chord content of a song's harmonic arrangement and enter it into the
Chord Track (Global Tracks) of a Logic Pro project.

Two phases: **extract** the harmony from files (cheap, exact), then **place** it
through Logic's UI (expensive, fragile). Do all the thinking in phase 1 so phase
2 is a mechanical loop the scripts can drive.

**Governing principle: never trust a click.** Every UI action here fails
silently — a missed menu row opens a submenu, a click a third of the way into a
bar lands the chord on the wrong beat, a lost focus types the chord name into
another application. None of these raise an error. Place, then *verify against
the ruler*, then continue.

`scripts/` does the mechanical work:

| Script | Does |
|---|---|
| `logic_ui.py` | click / drag / type / screenshot primitives, focus guard, full screen |
| `calibrate_lane.py` | measure bar1 + pixels-per-bar from ruler ticks; crop the lane to read |
| `chord_track.py` | create / rename / delete chord events |

Bootstrap once: `python3 -m venv venv && venv/bin/pip install pyobjc-framework-Quartz`

## Phase 1 — extract the harmony

1. Find the arrangement source (`.musicxml`/`.mxl` export, or the `.mscz` chord
   chart, which is the authority when both exist).
2. Read each `<harmony>`: measure number, `<root-step>` + `<root-alter>`,
   `<kind>`, any `<offset>`. From a `.mscz`, `<Harmony>` holds `<root>`/`<name>`
   as TPC integers — `step = "FCGDAEB"[(tpc+1) % 7]`, `alter = (tpc+1)//7 - 2`.
3. Confirm the score's meter matches the project's. If they differ, decide
   deliberately: changing the project meter re-times everything already in it.
4. **Map song bar → Logic bar.** Arrangements almost always start after an
   intro, so the offset is not zero: with a 4-bar intro, song bar 1 is Logic bar
   5. Write the mapping out explicitly and check it against the arrangement
   markers before placing anything.
5. Reduce to **change points only** — the Chord Track sustains until the next
   event, so repeats are noise. Sustain is also what makes intros, breaks and
   outros read as tonic without any event of their own.
6. Show the user the bar → chord list before entering it.

## Phase 2 — place the chords

```bash
# 1. Logic full screen -- mandatory, see "Focus" below
python -c "import scripts.logic_ui as u; u.fullscreen()"

# 2. calibrate, read the crop, then solve from two ruler ticks
scripts/calibrate_lane.py --verify --out /tmp/lane.png
scripts/calibrate_lane.py --solve --barA 1 --xA 25 --barB 33 --xB 1242

# 3. place -- highest bar first, handled internally
scripts/chord_track.py --bar1 574.7 --pxbar 22.42 --lane-y 374 \
    --create "5:A,6:E,7:D,8:A,9:F#7,10:Bm,11:E,12:A"

# 4. verify, fix, save
scripts/calibrate_lane.py --verify --out /tmp/after.png     # then READ it
```

Save with `Cmd+S` only once the lane reads correctly.

## The four rules that made this work

**1. Full screen, and check focus before every action.** If any other window
sits at the click point, the click activates *that* app and the chord name is
typed into it — this has leaked text into the user's editor and, with a stray
`Cmd+A`, selected and endangered their regions. `logic_ui.ensure_front()` guards
every step and aborts rather than typing blind.

**2. Work backwards through the bars.** Right-clicking the lane yields one of
two different menus with different item offsets, and a chord's drawn box has a
finite length, so you cannot predict which you will get. Placing from the
highest bar down means every click lands on empty lane, which always gives the
short menu — `Create Chord` at `+10`. On the long menu (click inside an existing
chord's box) `Create Chord` is at `+32` and `+10` is `Chord Progressions`, whose
submenu opens and creates nothing. `+42` on the short menu is `Paste`. Both
mistakes look identical to a missed click.

**3. Click ~2px right of the barline.** A click a quarter of the way in can land
the chord on a later beat or round it into the next bar. Do not try to fix this
by changing the project's grid/snap setting — that varies by project and zoom
and will not save a sloppy click. A small offset from the barline is correct
under any snap setting.

**4. Never send `Cmd+A` to the chord popup.** Its Chord field opens with the
text already selected, so just type. If focus is not in the field, `Cmd+A`
becomes a global Select All over the arrange window; the typing vanishes and a
later Delete destroys regions or tracks.

## Repairing what is already there

Prefer the cheapest fix:

- **Wrong name, right bar** → `--rename`. Uses `Edit Chord…` (`+54`, long menu).
- **Whole run off by one bar** → rename each in place rather than moving them.
  Three renames fixed a verse that had landed a bar late.
- **Genuinely surplus** → `--delete`, which selects the chord first and uses the
  menu's `Delete` item.

Do **not** drag chords to reposition them. A drag moves every *selected* chord,
so a stale `Select All Chords` silently shifts the entire progression sideways —
this happened twice and both times looked like a successful nudge.

Never press the Delete **key** to remove chords. With an unclear selection it
acts on the arrange window and has deleted a whole track. If you must, verify
the selection in a screenshot first, and `Cmd+Z` immediately if a track vanishes.

## Verifying

Read positions against **ruler ticks**, never against neighbouring chords.
`calibrate_lane.py --verify` crops the ruler and the Chord lane into one strip
so both are in the same image. Chord labels are drawn a few px inset from their
barline, so allow ~±0.2 bar. Recalibrate after any zoom, scroll, resize or
full-screen toggle — entering full screen shifts the layout ~12px vertically,
enough to put clicks in the Signature row instead of the Chord lane.

## Melody and other MIDI

**Do not use `File > Import > MIDI File…`.** It crashes Logic 11.0.1 reproducibly
— a Swift dynamic-cast failure in `CFileUtilIsInTrash` while the file dialog
checks Trash relationships. Two crashes, same stack.

Build the MIDI offline instead (place notes at absolute tick positions for the
target bars; a bar is `TPQ × beats-per-bar`) and bring it in by dragging from
Finder onto the target track, or hand the file to the user. Keep melody out of
the Chord Track — that track carries chord symbols only.

## Notes

- The process is **"Logic Pro X"**, not "Logic Pro". `pgrep -x "Logic Pro"`
  finds nothing and every System Events lookup fails.
- Accessibility exposes the **Control Bar only** — Tempo is an `AXSlider`
  (`AXIncrement`/`AXDecrement` move it in steps of 10, and its reported value
  lags, so set it by a known number of steps and verify visually), Time
  Signature an `AXPopUpButton` (`AXPress`, then arrow keys and Return; a
  *Change project signature / Insert new signature* dialog follows). The arrange
  canvas, context menus and chord popup expose **nothing** — all pixels.
- `ProjectData` inside a `.logicx` is binary. Never hand-edit it.
- Work on a **copy** of the user's template, never the template itself.
- An unsaved project is a free undo: nothing is committed until `Cmd+S`.
