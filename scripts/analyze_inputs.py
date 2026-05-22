#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from music21 import converter

from lyrics_syllabify import syllabify_lyrics
from music_analysis import analyze_score


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("arranged_score", type=Path, help="MusicXML/MIDI readable by music21")
    ap.add_argument("lyrics", type=Path)
    ap.add_argument("--language", default="English")
    ap.add_argument("--style", default="gentle children's song")
    ap.add_argument("--tempo-bpm", type=float, default=None)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    score = converter.parse(str(args.arranged_score))
    score_dict, music_warnings = analyze_score(score, tempo_bpm_override=args.tempo_bpm)
    lyrics_payload, lyric_warnings = syllabify_lyrics(args.lyrics, args.language)

    payload = {
        "score": score_dict,
        "lyrics": lyrics_payload["lyrics"],
        "warnings": [*music_warnings, *lyric_warnings],
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
