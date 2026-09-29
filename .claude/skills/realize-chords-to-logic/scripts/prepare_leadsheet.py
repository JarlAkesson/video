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
from music21 import converter, harmony, note, meter, stream, repeat


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

    # A repeat that begins on an upbeat leaves split bars once unrolled (SMOM 3 song 20:
    # 1.5 beats before the :| + the 0.5-beat upbeat): merge adjacent short bars that add
    # up to one full bar, or MuseScore pads each half to a full bar and shifts the rest.
    i = 1
    while i < len(ms) - 1:
        a, b = ms[i], ms[i + 1]
        qa, qb = a.duration.quarterLength, b.duration.quarterLength
        full = a.barDuration.quarterLength
        if qa < full and qb < full and qa + qb == full:
            ca, cb = containers(a), containers(b)
            if len(ca) != len(cb):
                sys.exit(f"bars {i + 1}/{i + 2}: cannot merge, voice counts differ")
            for x, y in zip(ca, cb):
                for e in [e for e in list(y.elements) if movable(e)]:
                    off = e.offset; y.remove(e); x.insert(qa + off, e)
            if ca[0] is not a:                       # symbols at measure level beside voices
                for e in [e for e in list(b.elements) if "ChordSymbol" in e.classes]:
                    off = e.offset; b.remove(e); a.insert(qa + off, e)
            part.remove(b); ms.pop(i + 1)
            print(f"merged split bars {i + 1}+{i + 2} ({qa}+{qb}q)")
        i += 1

    # An empty chord symbol (SMOM 4 song 6 bar 9 carries one beside its real F) parses as
    # "N.C." with no root: it states no harmony, so drop it rather than realize it.
    for cs in list(part.recurse().getElementsByClass("ChordSymbol")):
        if cs.root() is None:
            cs.activeSite.remove(cs)
            print(f"dropped empty chord symbol ({cs.figure})")

    # MuseScore can export an inversion's bass WITHOUT its accidental (SMOM 4 song 4:
    # E dim7, 2nd inversion, came out as bass "B" though the chord's fifth is B-flat).
    # music21 then keeps both spellings, so the chord gets a stray extra note and the
    # realization no longer matches the voicing rule. Make the bass a real chord tone.
    for cs in list(part.recurse().getElementsByClass("ChordSymbol")):
        b = cs.bass()
        if b is None or "/" not in cs.figure:
            continue
        head = cs.figure.rsplit("/", 1)[0]
        tones = [p.name for p in harmony.ChordSymbol(head).pitches]
        if b.name in tones:
            continue
        same = [n for n in tones if n[0] == b.name[0]]
        cs.figure = f"{head}/{same[0]}" if len(same) == 1 else head
        print(f"bass fixed: {b.name} -> {cs.figure}")

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
    last_q = last.barDuration.quarterLength   # the LAST bar's meter (differs in SMOM 3 song 17)
    d2 = last_q - last.duration.quarterLength
    if d2 > 0:                      # short final bar: rest at the end of each voice
        for c in containers(last):
            c.insert(c.highestTime, note.Rest(quarterLength=last_q - c.highestTime))
        last.paddingRight = 0
    for i, m in enumerate(ms, 1):
        m.number = i; m.numberSuffix = None
    wrong = [(m.number, m.duration.quarterLength) for m in ms
             if m.duration.quarterLength != m.barDuration.quarterLength]
    if wrong:                       # every later step assumes full bars
        sys.exit(f"bars still not full length (bar, quarters): {wrong}")
    new = stream.Score(); new.insert(0, part)
    new.write("musicxml", fp=out)
    ts = part.recurse().getElementsByClass("TimeSignature")[0]
    print(f"bars {n_before} -> {len(ms)}, meter {ts}, "
          f"bar {bar_q}q, pickup {pickup}, final bar padded {d2 > 0}")


if __name__ == "__main__":
    main()
