#!/usr/bin/env python3
"""Clean one raw OMR score into a trustworthy MusicXML file.

Applies, in order: melody selection, meter propagation, measure-length repair
(non-destructive -- a note is never deleted), anacrusis unpadding, trailing
all-rest-measure removal, marking strip, voice policy, tuplet bracketing,
time-signature dedup, and a verified write.

Examples
--------
  # melody only, the common case
  normalize_measures.py raw/song_01.mxl -o out/song_01.musicxml --melody-only \\
      --title "1. Videvisan" --composer "Alice Tegner"

  # melody + piano grand staff
  normalize_measures.py raw/song_01.mxl -o out/song_01.musicxml

  # whole folder
  normalize_measures.py raw/*.mxl --out-dir out --melody-only --suffix _v2

Tuplets are preserved by default (--no-triplets to quantise onto a binary grid
instead, which is only appropriate when a later pass rebuilds bars from a
binary duration set). Prints a one-line summary plus a count of each repair
applied; pass --json for machine-readable output.
"""

import argparse
import json
import os
import sys

import music21 as m21
from music21 import instrument, layout, stream

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import omrlib  # noqa: E402


def build(score, args, scope):
    allowed = omrlib.BINARY if args.no_triplets else omrlib.WITH_TRIPLETS

    melody, accomp = omrlib.pick_melody(score)
    if melody is None:
        raise SystemExit(f'{scope}: no usable part found')
    if args.melody_only:
        accomp = []

    parts = [melody] + accomp
    omrlib.infer_time_signature(parts, default=args.default_meter)
    omrlib.propagate_time_signature(parts)

    # Before any duration is touched: the Tuplet object will not survive the
    # repairs, but the fact that the engine saw one is the evidence we need.
    if not args.no_triplets:
        omrlib.tag_omr_tuplets(melody)
    omrlib.force_monophonic(melody)
    # Baseline for the invented-rhythm check: same note set as the output, with
    # the engraver's own durations, before any repair that could add an ornament.
    # Degenerate bars are recovered first -- their durations are noise until
    # rescaled, so censusing them earlier would understate the source and make
    # the recovery look like invention.
    omrlib.rescale_degenerate_bars(melody, scope)
    baseline = omrlib.census_stream(melody)
    for p in parts:
        omrlib.strip_fermatas(p)
        omrlib.strip_markings(p, dynamics=not args.keep_dynamics,
                              chord_symbols=not args.keep_chord_symbols)
        omrlib.unhide(p)

    # Measured before normalisation pads it: the anacrusis test needs the final
    # bar's real content length, not a padded one.
    last_music = omrlib.last_music_measure(melody)
    final_hint = omrlib.span(last_music) if last_music is not None else None

    omrlib.normalize_part(melody, allowed, monophonic=True, scope=f'{scope}:melody')
    for i, p in enumerate(accomp):
        omrlib.normalize_part(p, omrlib.BINARY, monophonic=False, scope=f'{scope}:acc{i}')

    pickup = omrlib.fix_anacrusis(melody, allowed, final_hint=final_hint, scope=scope, mode=args.anacrusis)
    for p in accomp:
        omrlib.fix_anacrusis(p, omrlib.BINARY, final_hint=final_hint, scope=scope, mode=args.anacrusis)

    out = stream.Score()
    omrlib.set_metadata(out, args.title, args.composer)
    melody.id = melody.partName = 'Melody'
    melody.partAbbreviation = 'Mel.'
    omrlib.strip_instruments(melody)
    melody.insert(0, instrument.Vocalist())
    out.insert(0, melody)

    if accomp:
        rh = stream.PartStaff()
        rh.id, rh.partName, rh.partAbbreviation = 'PianoRH', 'Piano', 'Pno.'
        rh.insert(0, instrument.Piano())
        for mm in accomp[0].getElementsByClass('Measure'):
            rh.append(mm)
        out.insert(0, rh)
        lh = None
        if len(accomp) > 1:
            lh = stream.PartStaff()
            lh.id, lh.partName, lh.partAbbreviation = 'PianoLH', 'Piano', 'Pno.'
            lh.insert(0, instrument.Piano())
            for mm in accomp[1].getElementsByClass('Measure'):
                lh.append(mm)
            out.insert(0, lh)
            out.insert(0, layout.StaffGroup([rh, lh], name='Piano',
                                            abbreviation='Pno.', symbol='brace'))
        # Only a single voice per staff survives a notation-program round trip.
        for p in (rh, lh):
            if p is not None:
                omrlib.enforce_single_voice(p, omrlib.BINARY)

    dropped = omrlib.drop_trailing_rest_measures(out, min_run=args.min_trailing_rests, scope=scope)
    for p in out.parts:
        omrlib.mark_tuplet_brackets(p)
        omrlib.dedupe_time_signatures(p)
    return out, pickup, dropped, baseline


def process(src, dst, args):
    scope = os.path.basename(src)
    omrlib.reset_log()
    score = omrlib.read_any(src)
    out, pickup, dropped, baseline = build(score, args, scope)

    ok, counts = omrlib.safe_write(out, dst, keep_breaks=args.keep_breaks)
    problems = omrlib.verify_xml(dst, os.path.basename(dst),
                                 max_voices=1 if args.melody_only else 2,
                                 allow_breaks=args.keep_breaks)
    notes, rests = omrlib.count_notes(dst)
    after = omrlib.census_xml(dst)
    invented = omrlib.invented_rhythm(baseline, after)
    for kind, n in invented.items():
        if n:
            problems.append(
                f'{os.path.basename(dst)}: INVENTED {n} {kind} '
                f'({baseline.get(kind, 0)} in source -> {after.get(kind, 0)} out) '
                f'-- see references/rare-repairs.md')
    return {
        'src': src, 'dst': dst,
        'rhythm_before': baseline, 'rhythm_after': after, 'invented': invented,
        'write_converged': ok, 'measure_counts': counts,
        'pickup_len': pickup, 'trailing_rest_measures_dropped': dropped,
        'notes': notes, 'rests': rests,
        'fixes': omrlib.log_summary(),
        'problems': problems,
    }


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('inputs', nargs='+', help='raw OMR .mxl/.musicxml files')
    # -o rather than a second positional: argparse gives every positional to a
    # greedy nargs='+' list, so a trailing output path is swallowed silently.
    ap.add_argument('-o', '--output', help='output file (single input only)')
    ap.add_argument('--out-dir', help='write here, keeping each input name')
    ap.add_argument('--suffix', default='', help='append to each output stem')
    ap.add_argument('--melody-only', action='store_true',
                    help='drop the accompaniment (cheaper and safer; see SKILL.md)')
    ap.add_argument('--no-triplets', action='store_true',
                    help='quantise onto a binary grid instead of preserving tuplets')
    ap.add_argument('--title'), ap.add_argument('--composer')
    ap.add_argument('--keep-dynamics', action='store_true')
    ap.add_argument('--keep-chord-symbols', action='store_true')
    ap.add_argument('--default-meter', default='4/4')
    ap.add_argument('--anacrusis', choices=('auto', 'always', 'never'), default='auto',
                    help="auto: unpad a rest-padded pickup only when pickup+final "
                         "completes one bar (default). always: unpad on shape alone, "
                         "rebarring upbeats the source wrote as full bars. never: off")
    ap.add_argument('--min-trailing-rests', type=int, default=2,
                    help='delete trailing all-rest measures once this many follow (default 2)')
    ap.add_argument('--keep-breaks', action='store_true',
                    help='keep the source page/system breaks (stripped by default: '
                         'they record where the SCAN broke, not the music)')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()

    jobs = []
    if args.out_dir:
        os.makedirs(args.out_dir, exist_ok=True)
        for src in args.inputs:
            stem = os.path.splitext(os.path.basename(src))[0] + args.suffix
            jobs.append((src, os.path.join(args.out_dir, stem + '.musicxml')))
    else:
        if len(args.inputs) != 1 or not args.output:
            ap.error('give one input with -o OUTPUT, or use --out-dir')
        jobs.append((args.inputs[0], args.output))

    results = [process(src, dst, args) for src, dst in jobs]

    if args.json:
        print(json.dumps(results, indent=2))
        return 1 if any(r['problems'] for r in results) else 0

    total_problems = 0
    for r in results:
        fixes = ', '.join(f'{k}={v}' for k, v in sorted(r['fixes'].items())) or 'none'
        flags = []
        if r['pickup_len']:
            flags.append(f"pickup={r['pickup_len']:g}")
        if r['trailing_rest_measures_dropped']:
            flags.append(f"dropped {r['trailing_rest_measures_dropped']} empty bar(s)")
        if not r['write_converged']:
            flags.append('WRITE DID NOT CONVERGE')
        print(f"{os.path.basename(r['dst']):48s} notes={r['notes']:4d} "
              f"{' '.join(flags)}")
        print(f"    fixes: {fixes}")
        for p in r['problems']:
            print('    !!', p)
        total_problems += len(r['problems'])
    print(f'\n{len(results)} file(s), {total_problems} verification problem(s)')
    return 1 if total_problems else 0


if __name__ == '__main__':
    raise SystemExit(main())
