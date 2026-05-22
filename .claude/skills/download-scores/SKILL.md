---
name: download-scores
description: Download music scores (sheet music, noter) for Swedish children's songs from a CSV file. Searches IMSLP, Musikverket, Internet Archive, MuseScore, and other sources. Saves downloads under assets/ with structured naming and produces a download report under assets/_build/.
allowed-tools: Read Bash Grep Glob Write WebSearch WebFetch Agent TodoWrite
argument-hint: [csv-file]
effort: max
---

# Download Music Scores for Swedish Children's Songs

You are a research agent. Your task is to systematically find and download music scores (sheet music, noter) for Swedish children's songs from the provided CSV file.

## Input

The CSV file path is provided as `$ARGUMENTS`. If no argument is given, look for a CSV file in the current working directory that contains song data (e.g., `songs.csv`, `barnvisor.csv`, or similar).

Read the CSV file first. Identify columns for: song number, song title, composer, and copyright status.

## Copyright Filter

- Songs marked FRI GLOBALT or FRI I EU/SE: search and download.
- Songs marked SKYDDAD (copyright protected): **skip entirely**. Do not attempt to download.

## Output Directory

For each song we want (in order of importance):

1. MusicXML/MXL
2. MIDI
3. PDF sheet
4. Lyrics text

MusicXML and MIDI are the most valuable: **either one should let us export the other, and also generate a PDF sheet** (via MuseScore). Lyrics still usually need to be found separately.

All *downloaded inputs* live under `assets/`:

- PDFs/images → `assets/sheets/`
- MIDI → `assets/midi/`
- MusicXML/MXL/MSCZ → `assets/xml/`
- Lyrics text → `assets/lyrics/`

All *derived conversions* (PDF→MXL, MIDI→MusicXML, etc.) live under `assets/_build/`.

Inside `assets/_build/` we mirror the same structure:

- `assets/_build/xml/` (derived MusicXML/MXL)
- `assets/_build/midi/` (derived MIDI)
- `assets/_build/sheets/` (derived PDF sheets)
- logs/reports under `assets/_build/reports/`

## Per-song decision policy

For each song:

1. **Try to download MusicXML or MIDI first.**
2. If you succeed, **export the rest from it**:
   - if primary is MIDI: export MusicXML + PDF sheet
   - if primary is MusicXML/MXL: export MIDI + PDF sheet
3. If any export step fails (missing tool, conversion error, etc.), **resort to downloading the missing artifacts separately** and **flag what failed** in the report.
4. If you cannot find any MIDI or MusicXML after best effort, **fall back to PDF + lyrics**, and move on to the next song.
5. If you tried your best and still couldn’t find the required artifacts, **move on** (do not get stuck).

## File Naming Convention

Every downloaded file must follow this pattern:

```
[number]_[song_name]_[source].[ext]
```

Example: `007_Ekorr_n_satt_i_granen_IMSLP.pdf`

- Use the number and name exactly as in the CSV.
- Replace spaces with `_`, strip special characters: å→a, ä→a, ö→o, '→nothing.
- Multiple files for the same song: append `_v1`, `_v2`, etc.

## Search Strategy — For Every Eligible Song

Check **all** of these sources:

1. **Svenskt visarkiv** (svensktvisarkiv.se) — can provide downloadable PDFs for many Swedish song collections (including Alice Tegnér pages and “Sök i samlingarna”).
2. **Wikimedia Commons** (commons.wikimedia.org) — PDFs and MIDIs (often from old songbooks/collections).
3. **IMSLP** (imslp.org) — public-domain scores/collections, including Swedish folk song categories.
4. **Projekt Runeberg / Arkivkopia** (runeberg.org / arkivkopia.se) — scanned books/songbooks as PDFs.
5. **Internet Archive** (archive.org) — scanned songbooks and collections.
6. **Musopen** (musopen.org) — public domain scores.
7. **OpenScore / Mutopia / CPDL** (openscore.cc / mutopiaproject.org / cpdl.org) — mostly classical/hymn-domain, but sometimes overlaps (useful when a “children’s song” is also a hymn tune/folk tune).
8. **MuseScore** (musescore.com) — community scores; treat license and arrangement provenance carefully.
9. **Mamalisa** (mamalisa.com) — often has MIDIs and lyrics for children’s songs (verify reuse/license suitability before publishing).
10. Generic web search: `[song title] noter PDF`, `[song title] filetype:mxl`, `[song title] filetype:mid`, and Swedish variants.

### Search Tips

- Try both original Swedish spelling and transliterated versions (å→a, ä→a, ö→o).
- Try variant titles — many songs have alternate names.
- If IMSLP requires navigating to a composer page first, do so.
- Do **not** download files behind paywalls or login walls.
- Verify each file is actually a score (not a webpage or lyrics-only page).
- Prefer sources that provide stable file URLs (direct `.pdf`, `.mid`, `.mxl`, `.musicxml`), not transient preview links.

## MIDI Files — Priority

MIDI files are especially valuable. If found, always download them. Name identically to PDFs but with `.mid` extension.

## MusicXML Files — Priority

If you can find MusicXML (`.musicxml`, `.mxl`) or MuseScore (`.mscz`) exports for a song, prefer downloading those first.

If only PDF sheet music is available, either skip it (for "XML only" runs) or download the PDF and (optionally) convert it to MusicXML using the repo’s Audiveris workflow. Note: PDF→XML OMR quality is often poor compared to direct exports.

## Direct-score-first workflow (implemented helper)

The repo includes a helper downloader (`download_scores`) that can:

- search the web for direct score files (MusicXML/MXL/MSCZ/MIDI) by title
- download the first matching direct score file (preferring XML over MIDI over PDF)
- optionally fall back to PDF and convert via Audiveris
- optionally convert MIDI→MusicXML via MuseScore (recommended when PDFs are disallowed)

Suggested usage:

```bash
./bin/download_scores songs.csv --search-direct --verify-downloads
```

To allow PDF fallback:

```bash
./bin/download_scores songs.csv --search-direct --convert-pdf-to-mxl
```

### Notes about search

- `--search-direct` uses best-effort DuckDuckGo HTML scraping. In some environments it may return **no results** (e.g. HTTP 403 blocks). In that case, prefer a curated CSV with direct URLs (e.g. `mamalisa.com/midi/...`, Wikimedia, GitHub).

## Score Collections

If you find a collection (e.g., "Sjung med oss Mamma" on Internet Archive) that contains multiple songs from the list:
- Download the whole collection.
- Note which songs it covers in the report.
- If possible, extract individual pages per song and save as separate files.

## Thoroughness Requirements

- Try at least 3-4 different sources and search queries before marking a song as NOT FOUND.
- If multiple versions or arrangements exist, download all of them.
- Quality matters more than speed. A thorough search that finds 80% is far more valuable than a fast search that finds 30%.

## Logging — For Each Song

Track progress with TodoWrite. For each song produce a log entry:

```
Song #[n]: [Title]
Status: FOUND / PARTIAL / NOT FOUND
Files downloaded:
  - [filename] | Source: [full URL] | Format: [PDF/MIDI/XML] | Notes: [...]
Search notes: [what you tried, what you found, why certain sources were skipped]
```

## Final Report

When done, produce `assets/_build/reports/download_scores/DOWNLOAD_REPORT.md` containing:

1. Total songs processed
2. Songs with at least one score found (with filenames)
3. Songs with only partial results
4. Songs where nothing was found (with notes on what was tried)
5. Score collections downloaded that cover multiple songs
6. MIDI files found
7. Recommendations for manual follow-up

## Context

The scores will be used to produce music accompaniment for a Swedish children's YouTube channel. Completeness and accuracy are critical.
