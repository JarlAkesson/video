#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from music21 import converter
from music21 import pitch as m21pitch


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _note_events_for_part(score, part_index_0: int):
    part = score.parts[part_index_0]
    for meas in part.getElementsByClass("Measure"):
        mnum = int(getattr(meas, "number", 0) or 0)
        if mnum <= 0:
            continue
        # Track beat position within measure in quarterLength units (1.0 == quarter note).
        cursor = 0.0
        for el in meas.notesAndRests:
            dur = float(el.quarterLength)
            if el.isRest:
                cursor += dur
                continue
            if el.isChord:
                # Take top note as a simple melody proxy.
                pitch = max(el.pitches, key=lambda p: p.midi)
            else:
                pitch = el.pitch
            yield {
                "measure": mnum,
                "start_beat": cursor + 1.0,
                "duration_beats": dur,
                "pitch": pitch.nameWithOctave,
            }
            cursor += dur


def _flatten_syllables(lyrics: dict) -> list[tuple[str, str]]:
    # Returns list of (line_id, syllable).
    out = []
    for line in lyrics.get("lines", []):
        lid = line["id"]
        for s in line.get("syllables", []):
            out.append((lid, s))
    return out


def _clean_word(token: str) -> str:
    t = re.sub(r"[^A-Za-z0-9']+", "", token)
    return t


def _pitch_midi(p: str) -> int:
    try:
        return int(m21pitch.Pitch(p).midi)
    except Exception:
        return 0


def _phrase_start_measures(score_info: dict) -> set[int]:
    out: set[int] = set()
    for ph in score_info.get("phrases", []) or []:
        measures = ph.get("measures")
        if isinstance(measures, list) and len(measures) == 2 and isinstance(measures[0], int):
            out.add(int(measures[0]))
    return out


def _anchor_score(
    note_events: list[dict],
    idx: int,
    phrase_starts: set[int],
    prev_midi: int | None,
) -> float:
    ne = note_events[idx]
    score = 0.0

    dur = float(ne["duration_beats"])
    score += min(2.5, 0.9 * dur)

    beat = float(ne["start_beat"])
    if abs(beat - 1.0) < 1e-6:
        score += 1.2
    elif abs(beat - 3.0) < 1e-6:
        score += 0.8
    elif abs(beat - 2.0) < 1e-6 or abs(beat - 4.0) < 1e-6:
        score += 0.2

    if int(ne["measure"]) in phrase_starts and abs(beat - 1.0) < 1e-6:
        score += 0.6

    midi = _pitch_midi(str(ne["pitch"]))
    if prev_midi is not None:
        delta = abs(midi - prev_midi)
        if delta >= 8:
            score += 0.8
        elif delta >= 5:
            score += 0.5
        elif delta == 0 and dur <= 1.0:
            score -= 0.4

    return score


def _choose_anchor_indices(note_events: list[dict], syllable_count: int, score_info: dict) -> list[int]:
    n = len(note_events)
    m = syllable_count
    if m <= 0 or n <= 0:
        return []
    if m >= n:
        return list(range(n))

    phrase_starts = _phrase_start_measures(score_info)
    # Force the first syllable to start on the first note.
    anchors: list[int] = [0]
    prev_midi = _pitch_midi(str(note_events[0]["pitch"]))

    # For remaining anchors, pick one per (roughly) equal segment with a local max score.
    for k in range(1, m):
        remaining_anchors = m - k
        # Ensure room for remaining anchors after this one.
        min_next = anchors[-1] + 1
        max_next = n - remaining_anchors
        if min_next > max_next:
            anchors.append(max(anchors[-1] + 1, n - 1))
            continue

        # Target position for this anchor based on uniform spacing.
        target = int(round(k * (n - 1) / (m - 1)))
        # Search in a window around the target, respecting monotonicity constraints.
        window = max(2, int(round(n / (m * 2))) + 2)
        lo = max(min_next, target - window)
        hi = min(max_next, target + window)
        if lo > hi:
            lo, hi = min_next, max_next

        best_i = lo
        best_s = float("-inf")
        for i in range(lo, hi + 1):
            s = _anchor_score(note_events, i, phrase_starts, prev_midi)
            if s > best_s:
                best_s = s
                best_i = i
        anchors.append(best_i)
        prev_midi = _pitch_midi(str(note_events[best_i]["pitch"]))

    # Ensure strictly increasing (can be violated by ties/rounding).
    for i in range(1, len(anchors)):
        if anchors[i] <= anchors[i - 1]:
            anchors[i] = min(n - (len(anchors) - i), anchors[i - 1] + 1)
    return anchors


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("music_analysis_json", type=Path)
    ap.add_argument("lyrics_json", type=Path, nargs="?", default=None)
    ap.add_argument("--score", type=Path, required=True)
    ap.add_argument("--cue", default="clear vocals, minimal melisma")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    music_analysis = _load_json(args.music_analysis_json)
    if args.lyrics_json is None:
        score_info = music_analysis["score"]
        lyrics_info = music_analysis["lyrics"]
    else:
        score_info = music_analysis["score"]
        lyrics_payload = _load_json(args.lyrics_json)
        lyrics_info = lyrics_payload["lyrics"]

    warnings: list[str] = []
    arrangement_notes: list[dict] = []

    # Select a melody candidate: highest singability, then highest note_count.
    candidates = list(score_info.get("melody_candidates", []))
    if not candidates:
        raise SystemExit("No melody_candidates found in analysis.json")
    candidates.sort(key=lambda c: (c.get("singability_score", 0.0), c.get("note_count", 0)), reverse=True)
    selected = candidates[0]
    selected_part_id = selected["source_part"]
    part_index_0 = int(selected_part_id.lstrip("P")) - 1

    score = converter.parse(str(args.score))
    if part_index_0 < 0 or part_index_0 >= len(score.parts):
        raise SystemExit(f"Selected part {selected_part_id} out of range for score with {len(score.parts)} parts.")

    note_events = list(_note_events_for_part(score, part_index_0))
    if not note_events:
        raise SystemExit(f"No note events found in selected melody part {selected_part_id}.")

    syllables = _flatten_syllables(lyrics_info)
    if not syllables:
        raise SystemExit("Lyrics syllables are empty.")

    # Alignment policy:
    # - If syllables >= notes: assign 1 syllable per note; drop trailing syllables with a warning.
    # - If syllables < notes: pick syllable-start "anchor notes" using a simple salience score
    #   (duration, beat, phrase starts, leaps), then slur intervening notes.
    events_out = []
    anchor_indices = _choose_anchor_indices(note_events, len(syllables), score_info)
    anchor_set = set(anchor_indices)

    syll_i = 0
    current_line_id = syllables[0][0]
    current_syl = syllables[0][1]
    for i, ne in enumerate(note_events, start=1):
        if i - 1 in anchor_set and syll_i < len(syllables):
            current_line_id, current_syl = syllables[syll_i]
            syll_i += 1
            is_slur = False
            lyric = current_syl
            word = _clean_word(lyric)
            line_id = current_line_id
        else:
            # Slurred continuation: do not repeat lyric text.
            is_slur = True
            lyric = ""
            word = ""
            line_id = current_line_id

        breath_after = False
        # Heuristic: breathe at the end of each 4-measure phrase.
        if ne["measure"] % 4 == 0 and abs((ne["start_beat"] - 1.0) + ne["duration_beats"] - 4.0) < 1e-6:
            breath_after = True

        events_out.append(
            {
                "id": f"v{i:03d}",
                "measure": ne["measure"],
                "start_beat": ne["start_beat"],
                "duration_beats": ne["duration_beats"],
                "pitch": ne["pitch"],
                "lyric": lyric,
                "word": word,
                "line_id": line_id,
                "phonemes": None,
                "is_slur": is_slur,
                "breath_after": breath_after,
            }
        )

    if len(syllables) > len(note_events):
        warnings.append(
            f"Not enough melody notes ({len(note_events)}) for lyric syllables ({len(syllables)}); trailing syllables were dropped."
        )

    payload = {
        "global": {
            "tempo_bpm": score_info["tempo_bpm"],
            "meter": score_info["meter"],
            "language": lyrics_info["language"],
            "style": args.cue,
        },
        "vocal_events": events_out,
        "arrangement_notes": arrangement_notes,
        "warnings": warnings,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
