#!/usr/bin/env python3
from __future__ import annotations

from music21 import key as m21key, meter as m21meter, roman, tempo as m21tempo


def _first_or_none(items):
    for item in items:
        return item
    return None



def analyze_score(score, tempo_bpm_override: float | None = None) -> tuple[dict, list[str]]:
    warnings: list[str] = []

    ts = _first_or_none(score.recurse().getElementsByClass(m21meter.TimeSignature))
    meter_str = ts.ratioString if ts is not None else "4/4"
    if ts is None:
        warnings.append("No time signature found; defaulting meter to 4/4.")

    ks = _first_or_none(score.recurse().getElementsByClass("KeySignature"))
    if ks is not None:
        try:
            key_obj = ks.asKey()
            key_str = f"{key_obj.tonic.name} {key_obj.mode}"
        except Exception:
            key_str = "C major"
            warnings.append("KeySignature found but could not be interpreted; defaulting key to C major.")
    else:
        try:
            analyzed = score.analyze("key")
            if isinstance(analyzed, m21key.Key):
                key_str = f"{analyzed.tonic.name} {analyzed.mode}"
            else:
                key_str = "C major"
                warnings.append("Key analysis returned unexpected type; defaulting key to C major.")
        except Exception:
            key_str = "C major"
            warnings.append("Key analysis failed; defaulting key to C major.")

    tempo_mark = _first_or_none(score.recurse().getElementsByClass(m21tempo.MetronomeMark))
    tempo_bpm = None
    if tempo_mark is not None and tempo_mark.number is not None:
        tempo_bpm = float(tempo_mark.number)
    if tempo_bpm_override is not None:
        tempo_bpm = float(tempo_bpm_override)
    if tempo_bpm is None:
        tempo_bpm = 110.0
        warnings.append("No tempo found in score; defaulting tempo_bpm to 110.")

    # Measures are easiest to count from the first part.
    first_part = score.parts[0] if len(score.parts) else None
    measure_count = 0
    if first_part is not None:
        measure_count = len(list(first_part.getElementsByClass("Measure")))
    if measure_count <= 0:
        measure_count = 1
        warnings.append("Could not determine measure count; defaulting measure_count to 1.")


    # Phrases: simple chunking into 4-measure phrases.
    phrases = []
    phrase_id = 1
    m = 1
    while m <= measure_count:
        end = min(measure_count, m + 3)
        phrases.append({"id": f"A{phrase_id}", "measures": [m, end]})
        phrase_id += 1
        m = end + 1

    # Harmony: chordify at downbeats and label with roman numeral in the inferred key.
    harmony = []
    try:
        key_for_roman = score.analyze("key")
        chordified = score.chordify()
        cpart = chordified.parts[0] if len(chordified.parts) else chordified
        for meas in cpart.getElementsByClass("Measure"):
            mnum = int(getattr(meas, "number", 0) or 0)
            if mnum <= 0:
                continue
            chord = _first_or_none(meas.recurse().getElementsByClass("Chord"))
            if chord is None:
                continue
            try:
                rn = roman.romanNumeralFromChord(chord, key_for_roman)
                chord_guess = rn.figure
            except Exception:
                chord_guess = chord.pitchedCommonName
            harmony.append({"measure": mnum, "beat": 1.0, "chord_guess": chord_guess})
    except Exception:
        warnings.append("Harmony analysis failed; leaving harmony empty.")

    score_dict = {
        "tempo_bpm": tempo_bpm,
        "meter": meter_str,
        "key": key_str,
        "measure_count": measure_count,
        "phrases": phrases,
        "harmony": harmony,
    }
    return score_dict, warnings
