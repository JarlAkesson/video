#!/usr/bin/python3
"""Normalize a lead sheet so every Logic bar lines up with a song bar.

usage: prepare_leadsheet.py <lead sheet .mscz|.musicxml> <out.musicxml>

  * repeats / voltas are unrolled (the MIDI and the chord list then follow the
    played form),
  * a short pickup bar is padded with a leading rest to a full bar (as in the
    user's SMOM 5 song 1: pickup = full bar of rests + the upbeat),
  * a short final bar is padded with a trailing rest,
  * leading bars without any note are dropped,
  * measures are renumbered 1..N (voices are handled when padding).
Prints: bars, meter, whether there was a pickup (-> --starts = first downbeat - 1).
"""
import os, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from realize_chords import MSCORE
from music21 import converter, note, meter, stream, repeat


def main():
    src, out = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    with tempfile.TemporaryDirectory() as t:
        xml = src
        if src.endswith((".mscz", ".mscx")):
            xml = os.path.join(t, "lead.musicxml")
            subprocess.run([MSCORE, "-o", xml, src], capture_output=True)
        s = converter.parse(xml)
    part = s.parts[0]
    n_before = len(part.getElementsByClass("Measure"))
    try:
        part = part.expandRepeats()
    except repeat.ExpanderException:
        pass
    ms = list(part.getElementsByClass("Measure"))
    bar_q = ms[0].barDuration.quarterLength
    # leading bars with no notes at all (e.g. SMOM 5 song 8's empty bar 1) are dropped
    while ms and not ms[0].recurse().notes:
        gone = ms.pop(0); part.remove(gone)
        for cls in ("Clef", "KeySignature", "TimeSignature"):
            got = gone.getElementsByClass(cls)
            if got and not ms[0].getElementsByClass(cls):
                ms[0].insert(0, got[0])

    def containers(m):
        vs = list(m.voices)
        return vs if vs else [m]

    def movable(e):
        return isinstance(e, note.GeneralNote) or "ChordSymbol" in e.classes

    pickup = False
    first = ms[0]
    d = bar_q - first.duration.quarterLength
    if d > 0:                       # short pickup: shift content right, rest in front
        pickup = True
        for c in containers(first):
            els = [(e.offset, e) for e in list(c.elements) if movable(e)]
            for off, e in els:
                c.remove(e)
            c.insert(0, note.Rest(quarterLength=d))
            for off, e in els:
                c.insert(off + d, e)
        for e in [e for e in list(first.elements) if "ChordSymbol" in e.classes]:
            off = e.offset; first.remove(e); first.insert(off + d, e)
        first.paddingLeft = 0
    last = ms[-1]
    d2 = bar_q - last.duration.quarterLength
    if d2 > 0:                      # short final bar: rest at the end of each voice
        for c in containers(last):
            c.insert(c.highestTime, note.Rest(quarterLength=bar_q - c.highestTime))
        last.paddingRight = 0
    for i, m in enumerate(ms, 1):
        m.number = i; m.numberSuffix = None
    new = stream.Score(); new.insert(0, part)
    new.write("musicxml", fp=out)
    ts = part.recurse().getElementsByClass("TimeSignature")[0]
    print(f"bars {n_before} -> {len(ms)}, meter {ts}, "
          f"bar {bar_q}q, pickup {pickup}, final bar padded {d2 > 0}")


if __name__ == "__main__":
    main()
