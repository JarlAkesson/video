#!/usr/bin/env python3
from __future__ import annotations

from music21 import key as m21key, meter as m21meter, roman, tempo as m21tempo


def _first_or_none(items):
    for item in items:
        return item
    return None


def _pitch_name_range(pitches) -> list[str]:
    if not pitches:
        return ["C4", "C4"]
    low = min(pitches)
    high = max(pitches)
    return [low.nameWithOctave, high.nameWithOctave]


def _density_score(part) -> float:
    total = 0.0
    sounded = 0.0
    for el in part.flat.notesAndRests:
        ql = float(el.quarterLength)
        total += ql
        if el.isNote or el.isChord:
            sounded += ql
    if total <= 1e-9:
        return 0.0
    return max(0.0, min(1.0, sounded / total))


def _singability_score(low_midi: int, high_midi: int) -> float:
    # Heuristic: favor roughly C4–A5 (60–81), penalize extremes and very wide ranges.
    target_low = 60
    target_high = 81
    width = max(0, high_midi - low_midi)
    low_pen = max(0, target_low - low_midi) / 24.0
    high_pen = max(0, high_midi - target_high) / 24.0
    width_pen = max(0, width - 21) / 36.0
    score = 1.0 - (0.9 * low_pen + 0.9 * high_pen + 0.6 * width_pen)
    return max(0.0, min(1.0, score))


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

    parts_out = []
    melody_candidates = []
    for idx, part in enumerate(score.parts, start=1):
        part_id = f"P{idx}"
        name = (part.partName or part.id or part_id).strip() if hasattr(part, "partName") else part_id
        name_l = name.lower()

        is_perc = any("drum" in (instr.partName or "").lower() for instr in part.getInstruments())
        pitches = []
        midi_vals = []
        note_count = 0
        for n in part.flat.notes:
            if n.isChord:
                for p in n.pitches:
                    pitches.append(p)
                    midi_vals.append(int(p.midi))
                note_count += len(n.pitches)
            else:
                # Some parts (notably percussion) may contain Unpitched events.
                pitch = getattr(n, "pitch", None)
                if pitch is None:
                    continue
                pitches.append(pitch)
                midi_vals.append(int(pitch.midi))
                note_count += 1

        role_guess = "percussion" if is_perc else "accompaniment"
        density = _density_score(part)
        if not is_perc and density <= 0.45:
            role_guess = "melody_candidate"

        range_names = _pitch_name_range(pitches)
        parts_out.append(
            {
                "id": part_id,
                "name": name_l,
                "range": range_names,
                "role_guess": role_guess,
                "density_score": density,
            }
        )

        if not is_perc:
            if midi_vals:
                sing = _singability_score(min(midi_vals), max(midi_vals))
            else:
                sing = 0.0
            melody_candidates.append(
                {
                    "source_part": part_id,
                    "measures": [1, measure_count],
                    "note_count": note_count,
                    "singability_score": sing,
                    "range": range_names,
                }
            )

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
        "parts": parts_out,
        "phrases": phrases,
        "harmony": harmony,
        "melody_candidates": melody_candidates,
    }
    return score_dict, warnings

