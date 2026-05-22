# Skill: `syllabify_lyrics`

## Purpose

Turn `lyrics.txt` into a structured `lyrics.json` that downstream tools can align against a melody.

This step is lyrics-only. It should not inspect or modify the score.

## Inputs

```text
lyrics.txt
```

Optional config:

```json
{
  "language_hint": "English"
}
```

## Core responsibilities

1. Read lyric lines (preserve original text for each line).
2. Tokenize into words/syllables.
3. Respect explicit hyphenation in the input (e.g., `Twin-kle`).
4. If no explicit hyphens are present, apply a deterministic heuristic syllabifier.
5. Emit `lyrics.json`.

## Output

Write `lyrics.json` matching `schemas/lyrics.schema.json`.

## Suggested CLI

```bash
./bin/syllabify_lyrics lyrics.txt --language English --out lyrics.json
```

## Failure modes

Warn (do not fail) if:

- the file is empty
- a line contains no usable tokens after cleanup
- syllabification is heuristic and may be inaccurate for the language
