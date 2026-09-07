#!/usr/bin/env python
"""Enter chords into Logic Pro's global Chord Track.

Geometry comes from the caller (see calibrate_lane.py): the screen x of bar 1,
the pixels per bar, and the y of the Chord lane. All three change whenever the
window is resized, zoomed, scrolled, or toggled full screen, so recalibrate
after any of those.

THE TWO CONTEXT MENUS
---------------------
Right-clicking the Chord lane gives one of two different menus, and the item
offsets differ. Clicking the wrong row is silent -- you hit "Paste" or open the
"Chord Progressions" submenu and no chord appears, which looks exactly like the
click having missed.

  SHORT menu -- point is on EMPTY lane:
      Create Chord                 +10
      Paste                        +42
      Select All Chords            +74

  LONG menu -- point is inside an existing chord's box:
      Chord Progressions           +10      <- submenu, not what you want
      Create Chord                 +32
      Edit Chord...                +54
      ... Cut / Copy / Paste ...
      Delete                      +206
      Select All Chords           +239

  All offsets are from the right-click point; x is always +54.

WHY `create` WORKS BACKWARDS
----------------------------
A chord's box has a finite drawn length (~4 bars), so "is a chord sounding here"
does NOT tell you which menu you will get. Placing chords from the HIGHEST bar
down means every right-click lands on still-empty lane, so the SHORT menu is
guaranteed and the +10 offset is always right. This is the single change that
made placement reliable.

WHERE TO CLICK INSIDE THE BAR
-----------------------------
Click ~2px right of the barline. Clicking a quarter or a third of the way into
the bar lands the chord on a later beat, or rounds it into the NEXT bar; both
failures are easy to miss because the chord still appears, just in the wrong
place. Do not rely on the project's grid/snap setting to rescue a sloppy click:
the setting varies per project and per zoom, and a small offset from the barline
is correct under any of them.
"""
import argparse, sys, time
sys.path.insert(0, __file__.rsplit("/", 1)[0])
import logic_ui as ui

NUDGE = 2          # px right of the barline
MENU_DX = 54
CREATE_SHORT, CREATE_LONG, EDIT, DELETE_ITEM = 10, 32, 54, 206


def bar_x(g, bar):
    return g.bar1 + (bar - 1) * g.pxbar + NUDGE


def _commit(sym, dismiss):
    ui.type_text(sym)
    ui.key(ui.RETURN)
    time.sleep(0.6)
    ui.click(*dismiss)          # inside Logic, clear of the popup
    time.sleep(0.6)


def create(g, chords, dismiss):
    """chords: {bar: symbol}. Placed highest bar first -- see module docstring."""
    out = []
    for bar in sorted(chords, reverse=True):
        if not ui.ensure_front():
            out.append(f"bar {bar}: ABORT, Logic lost focus"); break
        x = bar_x(g, bar)
        ui.click(x, g.lane_y, "right"); time.sleep(1.1)
        ui.click(x + MENU_DX, g.lane_y + CREATE_SHORT); time.sleep(1.9)
        _commit(chords[bar], dismiss)
        out.append(f"bar {bar:>3} -> {chords[bar]:<5} x={x:.0f}")
    return out


def rename(g, items, dismiss):
    """items: {screen_x_of_chord: new_symbol}. Uses the LONG menu's Edit Chord.

    Cheaper and far safer than delete+recreate when chords are merely misnamed
    or sit one bar out: three renames fixed a whole verse that was off by one.
    """
    out = []
    for x, sym in items.items():
        if not ui.ensure_front():
            out.append(f"x={x}: ABORT"); break
        ui.click(x, g.lane_y, "right"); time.sleep(1.2)
        ui.click(x + MENU_DX, g.lane_y + EDIT); time.sleep(1.9)
        _commit(sym, dismiss)
        out.append(f"x={x:.0f} -> {sym}")
    return out


def delete(g, xs, dismiss):
    """xs: screen x of each chord to remove.

    Uses the context menu's Delete, never the Delete KEY. With an unclear
    selection the key deletes whatever is selected in the arrange window -- it
    removed an entire track once. Left-click first so exactly one chord is
    selected, and screenshot to confirm before trusting the result.
    """
    out = []
    for x in xs:
        if not ui.ensure_front():
            out.append(f"x={x}: ABORT"); break
        ui.click(x, g.lane_y); time.sleep(0.9)
        ui.click(x, g.lane_y, "right"); time.sleep(1.2)
        ui.click(x + MENU_DX, g.lane_y + DELETE_ITEM); time.sleep(1.4)
        out.append(f"deleted at x={x:.0f}")
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bar1", type=float, required=True, help="screen x of bar 1")
    p.add_argument("--pxbar", type=float, required=True, help="pixels per bar")
    p.add_argument("--lane-y", type=float, required=True, help="screen y of the Chord lane")
    p.add_argument("--dismiss", default="1300,800", help="x,y inside Logic, clear of the popup")
    p.add_argument("--create", help='e.g. "5:A,6:E,7:D,8:A,9:F#7,10:Bm,11:E,12:A"')
    p.add_argument("--rename", help='screen-x:symbol pairs, e.g. "779:Bm,800:E"')
    p.add_argument("--delete", help="screen-x list, e.g. 841,905")
    a = p.parse_args()

    if ui.Q is None:
        sys.exit("pyobjc-framework-Quartz is required: pip install pyobjc-framework-Quartz")
    g = argparse.Namespace(bar1=a.bar1, pxbar=a.pxbar, lane_y=a.lane_y)
    dismiss = tuple(float(v) for v in a.dismiss.split(","))

    if not ui.ensure_front():
        sys.exit(f"Logic is not frontmost (front = {ui.frontmost()}). Run fullscreen() first.")

    if a.delete:
        for r in delete(g, [float(v) for v in a.delete.split(",")], dismiss): print(r)
    if a.rename:
        items = {float(k): v for k, v in (i.split(":", 1) for i in a.rename.split(","))}
        for r in rename(g, items, dismiss): print(r)
    if a.create:
        chords = {int(k): v for k, v in (i.split(":", 1) for i in a.create.split(","))}
        for r in create(g, chords, dismiss): print(r)
    print("NOW VERIFY: calibrate_lane.py --verify, and read the crop. Never assume.")


if __name__ == "__main__":
    main()
