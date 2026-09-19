#!/usr/bin/python3
"""Helper MIDI: the song's TONIC chord held for N lead-in bars, same voicing rule as
realize_chords.py, with meter and 120 BPM. Import it at bar 1 and drag it onto the
Chord Track so the bars before the song read as tonic, then delete the helper track.

usage: make_leadin.py <lead sheet .mscz|.musicxml> --bars N [--out FILE]   -> <stem>_leadin.mid
(also used for the tonic gaps between repeated sections: --bars 2 --out <stem>_tonic2.mid)
Tonic = music21 key analysis of the lead sheet; printed so it can be sanity-checked
against the first/last chord symbol.
"""
import argparse, os, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from realize_chords import voice, MSCORE
from music21 import converter, harmony, chord, meter, stream, tempo, key as m21key


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("--bars", type=int, required=True)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--out", help="output path (default <stem>_leadin.mid next to the source)")
    a = ap.parse_args()
    src = os.path.abspath(a.src)
    out = os.path.abspath(a.out) if a.out else os.path.join(
        os.path.dirname(src), os.path.splitext(os.path.basename(src))[0] + "_leadin.mid")
    if os.path.exists(out) and not a.force:
        sys.exit(f"{out} exists (use --force)")
    with tempfile.TemporaryDirectory() as t:
        xml = src
        if src.endswith((".mscz", ".mscx")):
            xml = os.path.join(t, "lead.musicxml"); subprocess.run([MSCORE, "-o", xml, src], capture_output=True)
        s = converter.parse(xml)
    k = s.analyze("key")
    figure = k.tonic.name + ("m" if k.mode == "minor" else "")
    syms = [c.figure for c in s.parts[0].flatten().getElementsByClass(harmony.ChordSymbol)]
    ts = s.parts[0].flatten().getElementsByClass(meter.TimeSignature)[0]
    bar_q = ts.barDuration.quarterLength
    print(f"key {k} -> tonic chord {figure}; first/last chord symbols {syms[0]} / {syms[-1]}; "
          f"meter {ts.ratioString}; {a.bars} bars = {a.bars * bar_q} quarters")
    cs = harmony.ChordSymbol(figure)
    p = stream.Part(); p.append(tempo.MetronomeMark(number=120)); p.append(ts)
    ch = chord.Chord([x for x in voice(cs)], quarterLength=a.bars * bar_q)
    p.append(ch)
    sc = stream.Score(); sc.append(p)
    sc.write("midi", fp=out)
    print(out)


if __name__ == "__main__":
    main()
