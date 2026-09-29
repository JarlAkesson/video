#!/usr/bin/python3
"""Create Chord Track events EXACTLY on the beat: playhead -> "+" on the Chord header.

usage (run with harmony2logic/venv/bin/python):
  chord_at_playhead.py --plus X Y --empty X Y  5:Dm 6:F 8.3:A ...

  --plus  X Y   screen POINTS of the "+" button in the Chord global-track header
  --empty X Y   screen points of empty track area (click dismisses the chord popover)
  specs         bar:name or bar.beat:name (from chord_spec.py)

For each spec: Navigate > Go To > Position "bar beat 1 1", click "+", type the name,
Return, click empty space. The chord is created at the playhead, so its start is the
exact tick -- unlike dropping a region on the Chord Track, whose analysed chords
start 20-40 ticks late (seen on SMOM 5 song 4: 5 1 1 20, 6 1 1 38).
"""
import argparse, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "harmony2logic", "scripts"))
import logic_ui as ui

ui.APP = "Logic Pro"
POPOVER_PIXEL = (2150, 640)   # inside the popover panel, dark arrange area otherwise


def se(body):
    ui.osa(f'tell application "System Events" to tell process "{ui.APP}"\n{body}\nend tell')


def popover_open():
    """True when the chord popover is up: its panel is light where the arrange is dark.

    It opens beside the playhead, so scan a band rather than one pixel (~163 inside the
    panel, ~65 over the arrange area).
    """
    import subprocess, tempfile
    from PIL import Image
    with tempfile.TemporaryDirectory() as t:
        p = os.path.join(t, "s.png")
        subprocess.run(["screencapture", "-x", p], check=True)
        px = Image.open(p).convert("L")
        for y in (560, 640, 720):
            run = 0
            for x in range(700, 2900, 40):
                run = run + 1 if 110 < px.getpixel((x, y)) < 200 else 0
                if run >= 8:            # ~320 px of panel in a row
                    return True
        return False


def windows():
    return ui.osa(f'tell application "System Events" to tell process "{ui.APP}" '
                  'to get name of every window')


def goto(bar, beat=1):
    """Playhead to bar/beat, only ever typing into the open Go To Position dialog.

    The menu click sometimes does not take. Typing the position anyway sent the digits
    to the arrange window as key commands, which moved the playhead somewhere else
    entirely - every chord after that landed on the wrong bar (SMOM 4 song 10).
    """
    ui.osa(f'tell application "{ui.APP}" to activate'); time.sleep(0.4)
    se("key code 53"); time.sleep(0.4)      # a popover still open swallows the menu click
    for _ in range(4):
        se('click menu item "Position…" of menu 1 of menu item "Go To" of menu 1 of '
           'menu bar item "Navigate" of menu bar 1')
        for _ in range(8):
            time.sleep(0.4)
            if "Go To Position" in windows():
                break
        else:
            continue
        break
    else:
        sys.exit("Go To Position dialog did not open")
    se(f'keystroke "{bar} {beat} 1 1"\ndelay 0.5\nkey code 36')
    time.sleep(0.9)
    if "Go To Position" in windows():
        sys.exit(f"Go To Position still open after typing {bar} {beat}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plus", nargs=2, type=float, required=True)
    ap.add_argument("--empty", nargs=2, type=float, required=True)
    ap.add_argument("specs", nargs="+")
    a = ap.parse_args()
    for spec in a.specs:
        pos, name = spec.split(":")
        bar, _, beat = pos.partition(".")
        # the PREVIOUS popover must be gone first: checking an open one that is really the
        # last chord's lets the name reach the arrange window instead (every other chord
        # was lost that way, the space in it starting playback)
        for _ in range(6):
            if not popover_open():
                break
            ui.key(53); time.sleep(0.6)
        else:
            sys.exit(f"previous chord popover stayed open before {spec}")
        goto(int(bar), int(beat or 1))
        # Type ONLY into an open popover. When the "+" click does not open it the name
        # reaches the arrange window as key commands - a space starts playback, and every
        # later chord then lands wherever the playhead has run to (SMOM 4 song 10).
        for _ in range(4):
            ui.click(*a.plus); time.sleep(1.4)
            if popover_open():
                break
        else:
            sys.exit(f"chord popover did not open for {spec}")
        # The popover opens UNFOCUSED and its first keystroke only gives the field focus:
        # "Gm" arrived as "m" and Logic committed its default C instead. A plain shift
        # press takes that hit (a leading space would reach the arrange window and start
        # playback, which then carried the playhead away from the next chord's bar).
        ui.osa('tell application "System Events" to key code 56'); time.sleep(0.4)
        ui.type_text(name); time.sleep(0.6)
        ui.key(36); time.sleep(1.2)
        ui.key(53); time.sleep(0.6)           # Escape closes the popover; clicking the
        ui.click(*a.empty); time.sleep(0.6)   # arrange area also deselects the new chord
        print("added", spec, flush=True)


if __name__ == "__main__":
    main()
