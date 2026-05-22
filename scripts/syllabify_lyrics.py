#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from lyrics_syllabify import syllabify_lyrics


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("lyrics", type=Path)
    ap.add_argument("--language", default="English")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    payload, _warnings = syllabify_lyrics(args.lyrics, args.language)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
