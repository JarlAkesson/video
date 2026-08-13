#!/usr/bin/env python3
"""Check finished scores against the clean-omr-transcription rules.

Reads the delivered bytes rather than re-parsing with music21, because
re-parsing applies its own interpretation (multirest expansion, voice gap
filling) and will both invent problems and hide real ones.

Checks per file:
  * no measure longer than its time signature
  * short measures only where legal (a pickup, and the final bar of a piece
    that has one)
  * rests only in each staff's FIRST voice
  * nothing hidden (no print-object="no"), no <multiple-rest>
  * at most --max-voices voices per staff
  * no page or system breaks (unless --allow-breaks)
  * no run of trailing all-rest measures

Examples
--------
  verify_score.py out/*.musicxml
  verify_score.py out/*.mscz --musescore "/Applications/MuseScore 4.app/Contents/MacOS/mscore"
  verify_score.py song.musicxml --also-mscz song.mscz     # check the round trip
  verify_score.py out/*.musicxml --json

Exit status is 1 if any problem was found, so it can gate a pipeline.
"""

import argparse
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import omrlib  # noqa: E402


def check_one(path, args, tmpdir):
    """Return (label, problems). .mscz is converted out first."""
    label = os.path.basename(path)
    extra = []
    allow_breaks = args.allow_breaks
    if path.lower().endswith('.mscz'):
        # Breaks are read from the .mscz itself, not from its MusicXML export:
        # MuseScore always marks every system it laid out in the export, so the
        # export cannot distinguish a stored break from automatic layout.
        if not allow_breaks:
            n = omrlib.mscz_layout_breaks(path)
            if n:
                extra.append(f'{label}: contains {n} stored layout break(s)')
        allow_breaks = True
        out = os.path.join(tmpdir, label + '.musicxml')
        if not omrlib.mscz_to_musicxml(path, out, args.musescore):
            return label, [f'{label}: MuseScore failed to convert']
        path = out
    return label, extra + omrlib.verify_xml(path, label, max_voices=args.max_voices,
                                            allow_breaks=allow_breaks)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('files', nargs='+', help='.musicxml / .mxl / .mscz to check')
    ap.add_argument('--max-voices', type=int, default=2,
                    help='voices allowed per staff (default 2; use 1 for melody-only)')
    ap.add_argument('--also-mscz', metavar='FILE', action='append', default=[],
                    help='additionally check these .mscz round trips')
    ap.add_argument('--allow-breaks', action='store_true',
                    help='permit page/system breaks (reported as problems by default)')
    ap.add_argument('--musescore', help='path to the MuseScore CLI')
    ap.add_argument('--json', action='store_true', help='machine-readable output')
    ap.add_argument('--quiet', action='store_true', help='only print the summary line')
    args = ap.parse_args()

    results = {}
    with tempfile.TemporaryDirectory() as tmp:
        for path in list(args.files) + list(args.also_mscz):
            label, problems = check_one(path, args, tmp)
            results[label] = problems

    total = sum(len(v) for v in results.values())
    if args.json:
        print(json.dumps({'files': len(results), 'problems': total, 'detail': results}, indent=2))
    else:
        if not args.quiet:
            for label, problems in results.items():
                if problems:
                    print(f'{label}: {len(problems)} problem(s)')
                    for p in problems:
                        print('   ', p)
        clean = len(results) - sum(1 for v in results.values() if v)
        print(f'{clean}/{len(results)} files clean, {total} problem(s)')
    return 1 if total else 0


if __name__ == '__main__':
    raise SystemExit(main())
