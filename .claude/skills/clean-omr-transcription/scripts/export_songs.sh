#!/bin/bash
# Export one raw MusicXML per song from a completed Audiveris .omr checkpoint.
#
# Usage:
#   export_songs.sh --omr BOOK.omr --out DIR --ranges "1:4 2:5 6:9-10 ..."
#                   [--audiveris PATH]
#
# --ranges is a space-separated list of songNumber:sheetRange, where the sheet
# range is whatever -sheets accepts (4, or 9-10). Verify the ranges against the
# source first with find_title_bands.py: a page-range split is only valid if no
# song starts mid-page.
#
# Audiveris ignores -output for .omr input and writes beside the book, as either
# <book>.mxl or <book>.mvtnull.mxl depending on whether it detected multiple
# Score objects. Both names are checked and the scratch file is cleared between
# songs -- otherwise every song silently overwrites the same file and you keep
# only the last one.
set -u

AUD="/Applications/Audiveris.app/Contents/MacOS/Audiveris"
OMR=""; OUT=""; RANGES=""
while [ $# -gt 0 ]; do
  case "$1" in
    --omr) OMR="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    --ranges) RANGES="$2"; shift 2 ;;
    --audiveris) AUD="$2"; shift 2 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
[ -n "$OMR" ] && [ -n "$OUT" ] && [ -n "$RANGES" ] || { sed -n '2,20p' "$0"; exit 2; }
[ -x "$AUD" ] || { echo "Audiveris not found at $AUD (pass --audiveris)" >&2; exit 2; }

OMRDIR=$(dirname "$OMR")
BASE=$(basename "$OMR" .omr)
mkdir -p "$OUT"
rm -f "$OUT"/*.mxl

fail=0
for spec in $RANGES; do
  n="${spec%%:*}"; sh="${spec##*:}"
  rm -f "$OMRDIR/$BASE.mvtnull.mxl" "$OMRDIR/$BASE.mxl"
  "$AUD" -batch -export -sheets "$sh" -- "$OMR" >/dev/null 2>&1
  src=""
  for cand in "$OMRDIR/$BASE.mvtnull.mxl" "$OMRDIR/$BASE.mxl"; do
    [ -f "$cand" ] && src="$cand" && break
  done
  if [ -n "$src" ]; then
    dst="$OUT/song_$(printf %02d "$n")_sheets_${sh}.mxl"
    cp "$src" "$dst"
    echo "song $n  sheets $sh  -> $(basename "$dst")  $(stat -f%z "$dst" 2>/dev/null || stat -c%s "$dst")B"
  else
    echo "song $n  sheets $sh  -> NO OUTPUT"
    fail=1
  fi
done
rm -f "$OMRDIR/$BASE.mvtnull.mxl" "$OMRDIR/$BASE.mxl"
exit $fail
