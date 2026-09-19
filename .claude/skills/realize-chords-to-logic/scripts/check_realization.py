#!/usr/bin/python3
"""Verify a realized score/MIDI: melody untouched, chord symbols identical on both
staves, every bar's block equals the voicing rule, block starts on the bar.
usage: check_realization.py <lead-sheet .mscz|.musicxml> <realized .mscz>"""
import os, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(__file__))
from realize_chords import voice, mscore
from music21 import converter, harmony, chord, note

lead, real = sys.argv[1:3]
with tempfile.TemporaryDirectory() as t:
    def xml(p):
        if p.endswith(".musicxml"): return p
        o = os.path.join(t, os.path.basename(p) + ".musicxml"); mscore("-o", o, p); return o
    L = converter.parse(xml(lead)).parts[0]; R = converter.parse(xml(real))
top, bot = R.parts
mel = lambda p: [(n.nameWithOctave, n.offset + m.offset, n.quarterLength)
                 for m in p.getElementsByClass("Measure") for n in m.flatten().notes if isinstance(n, note.Note)]
ok = True
def chk(label, cond):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + label)
chk("melody identical to lead sheet", mel(top) == mel(L))
bad = 0
for m in bot.getElementsByClass("Measure"):
    syms = sorted(m.flatten().getElementsByClass(harmony.ChordSymbol), key=lambda c: c.offset)
    blocks = sorted([c for c in m.flatten().getElementsByClass(chord.Chord) if not isinstance(c, harmony.ChordSymbol)],
                    key=lambda c: c.offset)
    tsyms = sorted(top.measure(m.number).flatten().getElementsByClass(harmony.ChordSymbol), key=lambda c: c.offset)
    if [s.figure for s in syms] != [s.figure for s in tsyms]: bad += 1; print("  symbols differ bar", m.number)
    if len(syms) != len(blocks): bad += 1; print("  symbol/block count differs bar", m.number); continue
    for s, b in zip(syms, blocks):
        if sorted(p.midi for p in b.pitches) != [p.midi for p in voice(s)] or b.offset != s.offset:
            bad += 1; print("  voicing/offset wrong bar", m.number, s.figure)
chk("chord staff = voicing rule, symbols match top staff", bad == 0)
sys.exit(0 if ok else 1)
