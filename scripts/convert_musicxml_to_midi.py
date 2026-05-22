#!/usr/bin/env python3
"""Convert MusicXML files to MIDI using music21.

Usage: python3 scripts/convert_musicxml_to_midi.py
Requires: music21
"""
import os
from pathlib import Path

try:
    from music21 import converter
except Exception as e:
    print('music21 not available. Install with: pip install music21')
    raise

ROOT = Path(__file__).resolve().parents[1]
XML_DIR = ROOT / "assets" / "xml"
MIDI_DIR = ROOT / "assets" / "_build" / "midi"
MIDI_DIR.mkdir(parents=True, exist_ok=True)

files = [
    XML_DIR / 'Bjornen_sover.musicxml',
    XML_DIR / 'Bjornen_sover_arranged.musicxml',
]

for f in files:
    if not f.exists():
        print(f'File not found: {f}')
        continue
    print(f'Parsing {f.name}...')
    score = converter.parse(str(f))
    outname = MIDI_DIR / (f.stem + '.mid')
    print(f'Writing MIDI to {outname}...')
    score.write('midi', fp=str(outname))

print('Done.')
