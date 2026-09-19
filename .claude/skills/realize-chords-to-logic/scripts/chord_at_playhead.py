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


def se(body):
    ui.osa(f'tell application "System Events" to tell process "{ui.APP}"\n{body}\nend tell')


def goto(bar, beat=1):
    ui.osa(f'tell application "{ui.APP}" to activate'); time.sleep(0.4)
    se('click menu item "Position…" of menu 1 of menu item "Go To" of menu 1 of '
       'menu bar item "Navigate" of menu bar 1')
    time.sleep(1.0)
    se(f'keystroke "{bar} {beat} 1 1"\ndelay 0.5\nkey code 36')
    time.sleep(0.9)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plus", nargs=2, type=float, required=True)
    ap.add_argument("--empty", nargs=2, type=float, required=True)
    ap.add_argument("specs", nargs="+")
    a = ap.parse_args()
    for spec in a.specs:
        pos, name = spec.split(":")
        bar, _, beat = pos.partition(".")
        goto(int(bar), int(beat or 1))
        ui.click(*a.plus); time.sleep(1.1)
        ui.type_text(name); time.sleep(0.4)
        ui.key(36); time.sleep(0.9)
        ui.click(*a.empty); time.sleep(0.5)
        print("added", spec, flush=True)


if __name__ == "__main__":
    main()
