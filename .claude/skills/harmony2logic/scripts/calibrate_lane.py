#!/usr/bin/env python
"""Measure the Chord lane's geometry, and crop it for verification.

Every placement failure in this skill's history traced back to bad geometry:
stale pixels-per-bar, a lane y that moved when the window changed, or reading a
chord's position against its neighbours instead of against the ruler. So:

  * Derive bar1/pxbar from TWO RULER TICK LABELS in a screenshot, never from
    where existing chords appear to sit.
  * Redo it after any zoom, scroll, resize, or full-screen toggle. Entering full
    screen (or the menu bar auto-revealing) shifts the whole layout ~12px
    vertically, which is enough to miss the lane entirely and click the
    Signature row or a track header instead.
  * Chord labels are drawn a few px inset from their barline, so allow ~±0.2 bar
    when checking a reading. Judge alignment against ruler ticks.

Usage
-----
  # 1. capture and crop the ruler + chord lane into one readable strip
  calibrate_lane.py --verify --out /tmp/lane.png

  # 2. read that image, note the x of two ruler labels and of the lane, then:
  calibrate_lane.py --solve --barA 1 --xA 25 --barB 33 --xB 1242 \
                    --crop-left 1120 --crop-width 1700 --shown 1450
"""
import argparse, subprocess, sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import logic_ui as ui


def retina_scale(shot):
    out = subprocess.run(["sips", "-g", "pixelWidth", shot],
                         capture_output=True, text=True).stdout
    px = int(out.strip().split(":")[-1])
    pts = int(subprocess.run(
        ["osascript", "-e",
         'tell application "Finder" to get bounds of window of desktop'],
        capture_output=True, text=True).stdout.strip().split(", ")[2])
    return px / pts if pts else 2.0


def to_screen(display_x, crop_left, crop_width, shown, scale=2.0):
    """Convert an x read off a cropped+upscaled image back to screen points."""
    full = crop_left + display_x * (crop_width / shown)
    return full / scale


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--verify", action="store_true", help="screenshot and crop the ruler+lane band")
    p.add_argument("--out", default="/tmp/lane.png")
    p.add_argument("--top", type=int, default=290, help="crop top in screenshot px")
    p.add_argument("--height", type=int, default=500)
    p.add_argument("--crop-left", type=int, default=1120)
    p.add_argument("--crop-width", type=int, default=1700)
    p.add_argument("--shown", type=int, default=1450, help="upscaled width of the crop")
    p.add_argument("--solve", action="store_true")
    p.add_argument("--barA", type=int); p.add_argument("--xA", type=float)
    p.add_argument("--barB", type=int); p.add_argument("--xB", type=float)
    p.add_argument("--lane-display-y", type=float,
                   help="y of the Chord lane as read in the crop")
    a = p.parse_args()

    if a.verify:
        raw = "/tmp/_logic_shot.png"
        ui.shot(raw)
        ui.crop(raw, a.out, a.top, a.crop_left, a.height, a.crop_width, a.shown)
        print(f"wrote {a.out} -- read it, then re-run with --solve using two ruler ticks")
        return

    if a.solve:
        if None in (a.barA, a.xA, a.barB, a.xB):
            sys.exit("--solve needs --barA/--xA and --barB/--xB")
        sA = to_screen(a.xA, a.crop_left, a.crop_width, a.shown)
        sB = to_screen(a.xB, a.crop_left, a.crop_width, a.shown)
        pxbar = (sB - sA) / (a.barB - a.barA)
        bar1 = sA - (a.barA - 1) * pxbar
        print(f"--bar1 {bar1:.1f} --pxbar {pxbar:.2f}")
        if a.lane_display_y is not None:
            y = (a.top + a.lane_display_y * (a.crop_width / a.shown)) / 2
            print(f"--lane-y {y:.0f}")
        print(f"# check: bar {a.barB} should sit at x={bar1 + (a.barB-1)*pxbar:.1f}")
        return

    p.print_help()


if __name__ == "__main__":
    main()
