#!/usr/bin/env python3
"""Mechanically extract tempo, meter, measure count, and per-part
name/range/density from a MusicXML file — no LLM judgment involved.

Usage:
    python3 extract_basic_metadata.py <path-to-musicxml>

Prints a JSON object to stdout:
{
  "tempo_bpm": 100.0 | null,
  "meter": "4/4" | null,
  "measure_count": 8,
  "parts": [
    {"id": "P1", "name": "Melody", "range": ["C4", "D5"], "note_count": 51, "density_score": 1.0}
  ]
}

Fields intentionally NOT covered here, since they require musical judgment
rather than mechanical extraction: key (needs the anacrusis/leading-tone/
final-note reasoning in basic_analysis's own instructions), phrase
boundaries, melody-candidate selection, role_guess.
"""
import json
import sys

import music21 as m21


def extract(path):
    score = m21.converter.parse(path)

    tempo_bpm = None
    for mm in score.recurse().getElementsByClass("MetronomeMark"):
        tempo_bpm = float(mm.number)
        break

    meter = None
    for ts in score.recurse().getElementsByClass("TimeSignature"):
        meter = ts.ratioString
        break

    parts_info = []
    max_note_count = 0
    for i, part in enumerate(score.parts):
        measures = part.getElementsByClass("Measure")
        notes = [n for n in part.recurse().notes]
        note_count = len(notes)
        max_note_count = max(max_note_count, note_count)

        pitches = []
        for n in notes:
            if n.isChord:
                pitches.extend(n.pitches)
            else:
                pitches.append(n.pitch)

        name = part.partName or part.id or f"P{i+1}"
        low = min(pitches).nameWithOctave if pitches else None
        high = max(pitches).nameWithOctave if pitches else None

        parts_info.append({
            "id": f"P{i+1}",
            "name": name,
            "range": [low, high],
            "note_count": note_count,
            "measure_count": len(measures),
        })

    for p in parts_info:
        p["density_score"] = round(p["note_count"] / max_note_count, 2) if max_note_count else 0.0

    measure_count = max((p["measure_count"] for p in parts_info), default=0)
    for p in parts_info:
        del p["measure_count"]

    return {
        "tempo_bpm": tempo_bpm,
        "meter": meter,
        "measure_count": measure_count,
        "parts": parts_info,
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: extract_basic_metadata.py <path-to-musicxml>", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(extract(sys.argv[1]), indent=2))
