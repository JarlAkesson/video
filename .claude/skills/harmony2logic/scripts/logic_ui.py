#!/usr/bin/env python
"""Primitives for driving Logic Pro by synthetic events.

Logic's arrange canvas, its context menus and the chord editor popup are all
INVISIBLE to Accessibility -- `AXMenu` lookups return nothing and there is no
element to press. Everything below the Control Bar therefore has to be driven by
real CGEvent mouse clicks at computed pixel positions.

Requires pyobjc:  python3 -m venv venv && venv/bin/pip install pyobjc-framework-Quartz

The process is named "Logic Pro X", NOT "Logic Pro" -- `pgrep -x "Logic Pro"`
finds nothing and every System Events lookup fails.
"""
import subprocess, sys, time

try:
    import Quartz as Q
except ImportError:
    Q = None

APP = "Logic Pro X"


def osa(script):
    return subprocess.run(["osascript", "-e", script],
                          capture_output=True, text=True).stdout.strip()


def frontmost():
    return osa('tell application "System Events" to return name of first process whose frontmost is true')


def ensure_front(timeout=6.0):
    """Raise Logic and confirm it owns the screen.

    This guard is not optional. If another window is in front at the click
    point, the click activates THAT app and every subsequent keystroke -- chord
    names included -- is typed into it. That has leaked text into the user's
    editor. Every action must be preceded by this check.
    """
    if frontmost() == APP:
        return True
    osa(f'tell application "{APP}" to activate')
    deadline = time.time() + timeout
    while time.time() < deadline:
        if frontmost() == APP:
            return True
        time.sleep(0.3)
    return False


def fullscreen():
    """Put Logic full screen so no other window can intercept a click.

    Do this before any chord work. The AX attribute sometimes reports False
    even once it has taken effect, so trust a screenshot, not the return value.
    Note the whole layout shifts ~12px vertically when full screen is entered or
    when the menu bar reveals itself -- recalibrate afterwards.
    """
    ensure_front()
    osa(f'tell application "System Events" to tell process "{APP}" '
        'to set value of attribute "AXFullScreen" of window 1 to true')
    time.sleep(6)


def _post(ev):
    Q.CGEventPost(Q.kCGHIDEventTap, ev)


def move(x, y):
    _post(Q.CGEventCreateMouseEvent(None, Q.kCGEventMouseMoved, (x, y), 0))
    time.sleep(0.08)


def click(x, y, button="left", clicks=1):
    if button == "left":
        down, up, btn = Q.kCGEventLeftMouseDown, Q.kCGEventLeftMouseUp, Q.kCGMouseButtonLeft
    else:
        down, up, btn = Q.kCGEventRightMouseDown, Q.kCGEventRightMouseUp, Q.kCGMouseButtonRight
    move(x, y)
    for i in range(1, clicks + 1):
        e = Q.CGEventCreateMouseEvent(None, down, (x, y), btn)
        Q.CGEventSetIntegerValueField(e, Q.kCGMouseEventClickState, i)
        _post(e); time.sleep(0.05)
        e = Q.CGEventCreateMouseEvent(None, up, (x, y), btn)
        Q.CGEventSetIntegerValueField(e, Q.kCGMouseEventClickState, i)
        _post(e); time.sleep(0.06)


def drag(x1, y1, x2, y2, steps=14):
    """Drag. Beware: dragging a chord drags EVERY selected chord.

    If a previous "Select All Chords" is still in force this silently shifts the
    whole progression sideways. Click empty lane to clear the selection first,
    and prefer rename/recreate over dragging.
    """
    move(x1, y1); time.sleep(0.2)
    _post(Q.CGEventCreateMouseEvent(None, Q.kCGEventLeftMouseDown, (x1, y1), Q.kCGMouseButtonLeft))
    time.sleep(0.35)
    for i in range(1, steps + 1):
        x = x1 + (x2 - x1) * i / steps
        y = y1 + (y2 - y1) * i / steps
        _post(Q.CGEventCreateMouseEvent(None, Q.kCGEventLeftMouseDragged, (x, y), Q.kCGMouseButtonLeft))
        time.sleep(0.05)
    time.sleep(0.3)
    _post(Q.CGEventCreateMouseEvent(None, Q.kCGEventLeftMouseUp, (x2, y2), Q.kCGMouseButtonLeft))
    time.sleep(0.3)


def type_text(s):
    """Type into the chord popup.

    NEVER send Cmd+A first. The popup's Chord field opens with its contents
    already selected, so typing replaces them. If the field happens not to hold
    focus, Cmd+A instead performs a global Select All over the arrange window --
    the typing then goes nowhere and a later Delete wipes whole regions or tracks.
    """
    osa(f'tell application "System Events" to keystroke "{s}"')
    time.sleep(0.55)


def key(code):
    osa(f'tell application "System Events" to key code {code}')
    time.sleep(0.3)


RETURN, ESCAPE, DELETE = 36, 53, 51


def shot(path):
    subprocess.run(["screencapture", "-x", path], check=True)
    return path


def crop(src, dst, top, left, height, width, scale=1450):
    """Crop a band out of a screenshot and upscale it for reading."""
    subprocess.run(["sips", "-c", str(height), str(width),
                    "--cropOffset", str(top), str(left), src, "--out", dst],
                   capture_output=True)
    subprocess.run(["sips", "-Z", str(scale), dst, "--out", dst], capture_output=True)
    return dst
