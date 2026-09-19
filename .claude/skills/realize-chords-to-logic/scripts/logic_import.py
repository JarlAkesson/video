#!/usr/bin/python3
"""Drive Logic Pro for the 'import MIDI, drag chord track into Chord Track' workflow.

  logic_import.py front                      restore + raise the Logic window
  logic_import.py shot [out.png]             raise Logic, capture, print px->pt scale
  logic_import.py import-midi FILE.mid [--tempo import|skip]
  logic_import.py goto BAR                   playhead to BAR 1 1 1 (Navigate > Go To > Position)
  logic_import.py move-to-playhead           Edit > Move > To Playhead on the SELECTED regions
  logic_import.py solo RX RY EX EY           select ONLY the region at (RX,RY): click empty
                                             space (EX,EY) first, then the region
  logic_import.py drag X1 Y1 X2 Y2           mouse drag, SCREEN POINTS (not pixels)

Uses System Events (Automation permission for the terminal/VS Code is required)
and the Quartz helpers of the harmony2logic skill for the mouse drag.
Process name on this machine is "Logic Pro" (harmony2logic hardcodes "Logic Pro X").
"""
import os, subprocess, sys, time

APP = "Logic Pro"


def osa(script):
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if r.returncode:
        sys.exit("osascript failed: " + r.stderr.strip())
    return r.stdout.strip()


def se(body):
    return osa(f'tell application "System Events" to tell process "{APP}"\n{body}\nend tell')


def front():
    """Logic gets minimized/covered by the editor; every action starts here."""
    osa(f'tell application "{APP}" to activate')
    try:
        se('set value of attribute "AXMinimized" of window 1 to false')
    except SystemExit:
        pass
    time.sleep(1.2)


def shot(out="/tmp/logic_shot.png"):
    front()
    subprocess.run(["screencapture", "-x", out], check=True)
    w = int(subprocess.run(["sips", "-g", "pixelWidth", out], capture_output=True, text=True)
            .stdout.split()[-1])
    small = out.replace(".png", "_1600.png")
    subprocess.run(["sips", "-Z", "1600", out, "--out", small], capture_output=True)
    pt_w = float(osa('tell application "Finder" to get item 3 of (get bounds of window of desktop)'))
    print(f"native {out} ({w}px)  view {small} (1600px wide)")
    print(f"screen point = pixel_in_1600_view * {pt_w / 1600:.4f}")


def import_midi(path, tempo="import"):
    path = os.path.abspath(path)
    assert os.path.exists(path), path
    front()
    # 1. playhead to bar 1: the import lands at the playhead
    se('click button "Go to Beginning" of group 1 of window 1')
    time.sleep(0.6)
    # 2. File > Import > MIDI File...
    se('click menu item "MIDI File…" of menu 1 of menu item "Import" of menu 1 of '
       'menu bar item "File" of menu bar 1')
    time.sleep(2)
    # 3. open panel: Cmd+Shift+G, type the full path, Return (selects), Return (Import)
    se('keystroke "g" using {command down, shift down}\ndelay 1\n'
       f'keystroke "{path}"\ndelay 1\nkey code 36\ndelay 1.5\nkey code 36')
    time.sleep(2.5)
    # 4. "Also import tempo information?" -- Import Tempo also brings the time signature
    label = "Import Tempo" if tempo == "import" else "No"
    se(f'click button "{label}" of window 1')
    time.sleep(3)
    print("imported", path, "| tempo:", tempo)


def goto(bar):
    front()
    se('click menu item "Position…" of menu 1 of menu item "Go To" of menu 1 of '
       'menu bar item "Navigate" of menu bar 1')
    time.sleep(1.2)
    se(f'keystroke "{int(bar)} 1 1 1"\ndelay 0.6\nkey code 36')
    time.sleep(1)


def move_to_playhead():
    """Regions right after an import are selected; this moves them all to the playhead."""
    front()
    se('click menu item "To Playhead" of menu 1 of menu item "Move" of menu 1 of '
       'menu bar item "Edit" of menu bar 1')
    time.sleep(1.2)


def solo(rx, ry, ex, ey):
    """Two regions are selected after an import; dragging both to the Chord Track
    shows 'Create Multiple Chord Groups' and drops nothing. A plain click on the
    region does NOT change the selection - clear it on empty space first."""
    front()
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.join(here, "..", "..", "harmony2logic", "scripts"))
    import logic_ui as ui
    ui.APP = APP
    ui.click(float(ex), float(ey)); time.sleep(1.0)
    ui.click(float(rx), float(ry)); time.sleep(1.0)


def drag(x1, y1, x2, y2):
    front()
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.join(here, "..", "..", "harmony2logic", "scripts"))
    import logic_ui as ui
    ui.APP = APP
    ui.drag(float(x1), float(y1), float(x2), float(y2))
    time.sleep(1.5)


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a: sys.exit(__doc__)
    cmd = a[0]
    if cmd == "front": front()
    elif cmd == "shot": shot(*a[1:2])
    elif cmd == "import-midi":
        t = a[a.index("--tempo") + 1] if "--tempo" in a else "import"
        import_midi(a[1], t)
    elif cmd == "goto": goto(a[1])
    elif cmd == "move-to-playhead": move_to_playhead()
    elif cmd == "solo": solo(*a[1:5])
    elif cmd == "drag": drag(*a[1:5])
    else: sys.exit(__doc__)
