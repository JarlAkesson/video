#!/usr/bin/python3
"""Print the Chord Track change list for a song laid out in Logic.

usage: chord_spec.py <lead sheet .mscz|.musicxml> --starts 5[,15,25] [--leadin-bar 1]

Each section is the whole song starting at a Logic bar (--starts). Bars before the
first section, and any gap between sections, hold the tonic. Only CHANGE points (plus every
section's first downbeat) are printed (the Chord Track sustains), as `bar:name` or `bar.beat:name`, ready for
chord_at_playhead.py. Beat is 1-based in the song's meter (quarter-note beats for
x/4; eighth-note beats for x/8).
"""
import argparse, os, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from realize_chords import MSCORE
from music21 import converter, harmony, meter


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--starts", required=True, help="comma list of Logic bars where each section starts")
    ap.add_argument("--leadin-bar", type=int, default=1)
    a = ap.parse_args()
    src = os.path.abspath(a.src)
    with tempfile.TemporaryDirectory() as t:
        xml = src
        if src.endswith((".mscz", ".mscx")):
            xml = os.path.join(t, "lead.musicxml")
            subprocess.run([MSCORE, "-o", xml, src], capture_output=True)
        s = converter.parse(xml)
    part = s.parts[0]
    k = s.analyze("key")
    tonic = k.tonic.name.replace("-", "b") + ("m" if k.mode == "minor" else "")
    ts = part.flatten().getElementsByClass(meter.TimeSignature)[0]
    beat_q = 4 / ts.denominator
    measures = list(part.getElementsByClass("Measure"))
    first_no = measures[0].number
    song = []                                   # (song bar index from 0, beat, name)
    for m in measures:
        for c in m.flatten().getElementsByClass(harmony.ChordSymbol):
            name = c.figure.replace("-", "b")
            song.append((m.number - first_no, 1 + c.offset / beat_q, name))
    events = [(a.leadin_bar, 1.0, tonic)]
    starts = [int(x) for x in a.starts.split(",")]
    for st in starts:
        for bar_i, beat, name in song:
            events.append((st + bar_i, beat, name))
        end = st + len(measures)
        events.append((end, 1.0, tonic))        # tonic after each section (gap / ending)
    at = {}
    for bar, beat, name in events:              # same position: the later (section) event wins
        at[(bar, beat)] = name
    out, cur = [], None
    for (bar, beat), name in sorted(at.items()):
        if name == cur and not (beat == 1 and bar in starts):   # always mark section starts
            continue
        cur = name
        out.append(f"{bar}:{name}" if beat == 1 else f"{bar}.{beat:g}:{name}")
    print(f"# key {k}, tonic {tonic}, meter {ts.ratioString}, {len(measures)} bars per section",
          file=sys.stderr)
    print(" ".join(out))


if __name__ == "__main__":
    main()
