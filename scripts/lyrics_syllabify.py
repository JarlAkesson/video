#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path


_VOWELS = set("aeiouy")
_EXCEPTIONS_EN: dict[str, list[str]] = {
    # Small set of hand-tuned splits to make common demo material behave well.
    "twinkle": ["twin", "kle"],
    "little": ["lit", "tle"],
    "above": ["a", "bove"],
    "diamond": ["dia", "mond"],
}


def _clean_token(token: str) -> str:
    return re.sub(r"[^A-Za-z0-9'\\-]+", "", token).strip()


def _split_on_vowel_groups(word: str) -> list[str]:
    # Very small heuristic syllabifier:
    # - preserves explicit hyphens
    # - otherwise splits around vowel groups with a few English-ish tweaks
    w = word
    w_l = word.lower()
    if "-" in w:
        return [p for p in w.split("-") if p]
    if w_l in _EXCEPTIONS_EN:
        parts = _EXCEPTIONS_EN[w_l]
        if w[:1].isupper():
            parts = [parts[0][:1].upper() + parts[0][1:], *parts[1:]]
        return parts

    # Keep apostrophes but ignore for vowel grouping.
    w_for_scan = w_l.replace("'", "")
    if not w_for_scan:
        return []

    # Find vowel groups.
    groups: list[tuple[int, int]] = []
    i = 0
    n = len(w_for_scan)
    while i < n:
        if w_for_scan[i] in _VOWELS:
            j = i + 1
            while j < n and w_for_scan[j] in _VOWELS:
                j += 1
            groups.append((i, j))
            i = j
        else:
            i += 1

    if len(groups) <= 1:
        return [w]

    # Silence a terminal 'e' if it is its own vowel group.
    if w_for_scan.endswith("e") and groups and groups[-1] == (n - 1, n):
        # Avoid silencing the 'e' in consonant+le endings (e.g., twinkle, little).
        keep_le = n >= 3 and w_for_scan.endswith("le") and (w_for_scan[n - 3] not in _VOWELS)
        if not keep_le:
            groups = groups[:-1]
            if len(groups) <= 1:
                return [w]

    # Create split points between groups.
    splits = []
    for (a0, a1), (b0, _b1) in zip(groups, groups[1:]):
        # consonant cluster between vowel groups
        mid = a1
        cluster = w_for_scan[a1:b0]
        if not cluster:
            splits.append(b0)
            continue
        # Put last consonant with next syllable when possible (CV onset).
        # E.g. won-der, lit-tle, twin-kle.
        cut = b0 - 1 if len(cluster) >= 2 else b0
        splits.append(cut)

    parts: list[str] = []
    start = 0
    for cut in splits:
        part = w[start:cut]
        if part:
            parts.append(part)
        start = cut
    tail = w[start:]
    if tail:
        parts.append(tail)
    return parts if parts else [w]


def syllabify_lyrics(path: Path, language: str) -> tuple[dict, list[str]]:
    text = path.read_text(encoding="utf-8").strip()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    warnings: list[str] = []

    out_lines = []
    for i, ln in enumerate(lines, start=1):
        raw_tokens = ln.replace(",", " ").replace(".", " ").replace(";", " ").replace(":", " ").split()
        syllables: list[str] = []
        for tok in raw_tokens:
            tok = _clean_token(tok)
            if not tok:
                continue
            syllables.extend(_split_on_vowel_groups(tok))
        out_lines.append({"id": f"L{i}", "text": ln, "syllables": syllables, "syllable_count": len(syllables)})

    if not out_lines:
        warnings.append("Lyrics file had no non-empty lines.")

    payload = {"lyrics": {"language": language, "lines": out_lines}, "warnings": warnings}
    return payload, warnings
