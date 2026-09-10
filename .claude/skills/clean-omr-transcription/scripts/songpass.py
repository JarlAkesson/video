#!/usr/bin/env python3
"""One call per song: everything the melody table needs, read off the page.

This exists because the per-song reconnaissance was the same eight commands
every time -- barscan on each system, pianobars on each system, duet_skyline
and the piano sonorities from the OMR -- and stitching their output together by
hand was most of the cost of a song.  Song 14 took four separate scan passes
and six image renders before the table could be written; almost none of that
was judgment, it was clerical work.

So: `songpass.py 15` reads song_map.tsv, walks every system of every page the
song occupies, and writes one report to work/sNN_pass.txt holding

  * the real barlines of each system, and the noteheads grouped into bars,
    with pitch, hollow/filled, dots and stacks -- the printed melody
  * the same for the accompaniment staves, clustered into sonorities and named
  * the OMR's per-measure skyline and per-offset accompaniment, for rhythm

and prints a digest: bars per system, the running piece-bar numbering, any bar
wider than its neighbours (which is what a missed barline looks like), and
whether the page's bar count reconciles with the OMR's measure count.

The two readings are deliberately kept side by side rather than merged.  This
book's OMR is reliable for RHYTHM and unreliable for pitch, octave, dots and
accidentals; the scan is the other way round.  Where they agree a bar is
settled with no image at all.  Where they disagree, that bar -- and only that
bar -- is worth rendering.

usage: songpass.py 15 [--staves 3] [--key -1] [--dpi 2000] [--x 0.09,0.95]
"""
import argparse
import csv
import os
import sys

from music21 import chord, converter, pitch, stream

import sys
sys.path.insert(0, __import__('os').path.dirname(
    __import__('os').path.abspath(__file__)))
from read_heads import scan_chunked
from staff_comb import systems
from staffdump import bar_candidates

# The book's own files -- song_map.tsv, book/songNN.mxl, work/ -- live in the
# book's build directory, which is where this is run from.  Only the code is
# in the skill.
HERE = os.environ.get('OMR_BOOK') or os.getcwd()
MAP = os.path.join(HERE, 'song_map.tsv')


def song_row(num):
    with open(MAP) as fh:
        for r in csv.DictReader(fh, delimiter='\t'):
            if int(r['song']) == num:
                return r
    raise SystemExit(f'song {num} not in song_map.tsv')


def pages_of(row):
    v = row['pdf_pages']
    if '-' in v:
        a, b = v.split('-')
        return list(range(int(a), int(b) + 1))
    return [int(v)]


def cluster(heads, tol):
    """Group heads that share an x into one printed event."""
    out = []
    for h in sorted(heads, key=lambda h: h['xfrac']):
        if out and h['xfrac'] - out[-1][-1]['xfrac'] < tol:
            out[-1].append(h)
        else:
            out.append([h])
    return out


def barlines(page, lines, H, lo, hi, hx):
    """bar_candidates minus the note stems: a stem stands at a head's own x."""
    cands = [c[0] for c in bar_candidates(page, lines, H, lo, hi,
                                          dpi=600, cover=0.90)]
    tol = 0.0
    if len(hx) > 1:
        gaps = sorted(hx[i + 1] - hx[i] for i in range(len(hx) - 1))
        big = [g for g in gaps if g > 0.004] or gaps
        tol = 0.22 * big[len(big) // 2]
    keep, out = [c for c in cands if not any(abs(c - x) < tol for x in hx)], []
    for b in keep:
        if out and b - out[-1] < max(tol, 0.004):
            continue                       # the two lines of a double barline
        out.append(b)
    return out


def head_token(grp):
    grp = sorted(grp, key=lambda h: -h['step'])
    tag = ''
    if grp[0]['dot'] is not None:
        tag += '.'
    if grp[0]['hollow']:
        tag += 'o'
    if any(g['frac'] > 0.28 for g in grp):
        tag += '?'
    return '+'.join(g['name'] for g in grp) + tag


def sonority_token(grp):
    names = sorted({h['name'] for h in grp}, key=lambda z: pitch.Pitch(z).midi)
    pcs = sorted({pitch.Pitch(z).pitchClass for z in names})
    return f"{','.join(names)} [{chord.Chord(pcs).pitchedCommonName}]"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('song', type=int)
    ap.add_argument('--staves', type=int, default=3,
                    help='staves per system: 3 for voice+piano, 2 for the '
                         'two-part choral on PDF p28')
    ap.add_argument('--key', type=int, default=0, help='sharps, negative=flats')
    ap.add_argument('--dpi', type=int, default=2000)
    ap.add_argument('--x', default='0.09,0.95')
    ap.add_argument('--range', default='-6,10', help='melody step window')
    ap.add_argument('--barlen', type=float, default=None,
                    help='quarterLengths per bar, for the OMR skyline')
    a = ap.parse_args()

    row = song_row(a.song)
    lo, hi = [float(v) for v in a.x.split(',')]
    rlo, rhi = [float(v) for v in a.range.split(',')]
    out = []
    digest = []
    piece_bar = 0

    for page in pages_of(row):
        st, H, _thr = systems(page, per=a.staves)
        nsys = len(st) // a.staves
        for sysno in range(1, nsys + 1):
            lines = st[(sysno - 1) * a.staves]
            mel, err, info = scan_chunked(page, sysno, a.staves, 0, lo, hi,
                                          'treble', a.key, a.dpi,
                                          lo_step=rlo, hi_step=rhi)
            if err:
                out.append(f'p{page} s{sysno}: melody scan failed: {err}')
                continue
            hx = sorted({round(h['xfrac'], 4) for h in mel})
            bl = barlines(page, lines, H, lo, hi, hx)
            tol = 0.0035
            edges = [lo] + bl + [hi]

            acc = []
            for staff in range(1, a.staves):
                clf = 'bass' if (a.staves == 3 and staff == 2) else 'treble'
                hs, e2, _ = scan_chunked(page, sysno, a.staves, staff, lo, hi,
                                         clf, a.key, a.dpi, lo_step=-8,
                                         hi_step=12)
                if e2:
                    out.append(f'p{page} s{sysno} staff{staff}: {e2}')
                else:
                    acc += hs

            out.append(f'--- p{page} sys{sysno}   space={info["space"]:.0f}px '
                       f'skew={info["skew"]:.0f}px   {len(mel)} melody heads')
            out.append('barlines: ' + ' '.join(f'{b:.4f}' for b in bl))
            widths = [edges[i + 1] - edges[i] for i in range(len(edges) - 1)]
            med = sorted(w for w in widths if w > 0.01)
            med = med[len(med) // 2] if med else 0
            nbars = 0
            for i in range(len(edges) - 1):
                x0, x1 = edges[i], edges[i + 1]
                # A span outside the outermost barlines is never a bar: the one
                # on the left is the system head (clef, key, and on a song's
                # first system the time signature -- whose two digits read as a
                # dyad on every staff, which is what the phantom B4+F#4 at the
                # start of song 14 turned out to be), the one on the right is
                # blank paper past the closing barline.  Excluding them is what
                # makes the count reconcile: song 14's 39 spans are 33 bars plus
                # three heads and three tails.
                head = bool(bl) and x1 <= bl[0] + 1e-9
                tail = bool(bl) and x0 >= bl[-1] - 1e-9
                mi = [h for h in mel if x0 - 1e-9 <= h['xfrac'] < x1]
                ai = [h for h in acc if x0 - 1e-9 <= h['xfrac'] < x1]
                if not mi and not ai and x1 - x0 < 0.02:
                    continue
                # A system's LAST barline often falls at or past the x window's
                # right edge and so is not detected at all, which leaves the
                # final bar looking like a tail -- song 14's bar 15 is one.  So
                # a tail has to be empty of melody as well as past the last
                # barline.  The cost is that a melody-rest bar at a system end
                # whose closing barline was missed gets dropped; the OMR
                # reconcile line below is what catches that.
                if tail and mi:
                    tail = False
                if head or tail:
                    kind = 'system head' if head else 'past final barline'
                    out.append(f'  span{i + 1:>2} [{x0:.4f}-{x1:.4f}] '
                               f'w={x1 - x0:.4f}  ({kind}, not a bar)')
                    if mi:
                        out.append('      mel: ' + '  '.join(
                            f'{head_token(g)}@{g[0]["xfrac"]:.4f}'
                            for g in cluster(mi, tol)))
                    continue
                nbars += 1
                piece_bar += 1
                wide = '   <-- WIDE, missed barline?' if med and (x1 - x0) > 1.6 * med else ''
                out.append(f'  span{i + 1:>2} [{x0:.4f}-{x1:.4f}] '
                           f'w={x1 - x0:.4f}  (piece bar ~{piece_bar}){wide}')
                if mi:
                    out.append('      mel: ' + '  '.join(
                        f'{head_token(g)}@{g[0]["xfrac"]:.4f}' for g in cluster(mi, tol)))
                for g in cluster(ai, tol):
                    out.append(f'      acc @{g[0]["xfrac"]:.4f} {sonority_token(g)}')
            digest.append(f'p{page} s{sysno}: {nbars} spans with content')

    # ---- the OMR side: rhythm, which the scan cannot give
    mxl = os.path.join(HERE, 'book', f'song{a.song:02d}.mxl')
    omr_bars = None
    if os.path.exists(mxl):
        sc = converter.parse(mxl)
        mel_part = sc.parts[0]
        ms = list(mel_part.getElementsByClass(stream.Measure))
        omr_bars = len(ms)
        # Audiveris does not always emit a time signature -- song 13's file has
        # none -- so fall back to the longest measure it wrote, which for this
        # book's OMR is a full bar even when shorter ones are defective.
        barlen = a.barlen
        if barlen is None:
            ts = mel_part.recurse().getElementsByClass('TimeSignature')
            if len(ts):
                barlen = float(ts[0].barDuration.quarterLength)
            else:
                barlen = max([float(m.highestTime) for m in ms] or [4.0])
        out.append('')
        out.append(f'--- OMR skyline (part 0, barlen {barlen})')
        for m in ms:
            vs = list(m.getElementsByClass(stream.Voice)) or [m]
            ev, onsets = [], set()
            for v in vs:
                for n in v.notesAndRests:
                    o = round(float(n.offset), 4)
                    if n.isRest:
                        nm = 'r'
                    else:
                        ps = getattr(n, 'pitches', None) or (n.pitch,)
                        nm = max(ps, key=lambda q: q.midi).nameWithOctave
                    ev.append((o, nm))
                    onsets.add(o)
            seq = []
            for i, o in enumerate(sorted(onsets)):
                nxt = sorted(onsets)[i + 1] if i + 1 < len(onsets) else barlen
                top = [nm for oo, nm in ev if oo == o]
                seq.append(f'{top[0]}:{round(nxt - o, 4)}')
            out.append(f'  m{m.number:>2} ' + ' '.join(seq))
        if len(sc.parts) > 1:
            out.append('')
            out.append('--- OMR accompaniment per offset')
            for m in mel_part.getElementsByClass(stream.Measure):
                by = {}
                for p in sc.parts[1:]:
                    mm = p.measure(m.number)
                    if mm is None:
                        continue
                    for n in mm.recurse().notes:
                        o = round(float(n.offset), 2)
                        for x in (n.pitches if isinstance(n, chord.Chord) else (n.pitch,)):
                            by.setdefault(o, set()).add(x.nameWithOctave)
                segs = []
                for o in sorted(by):
                    ps = sorted(by[o], key=lambda z: pitch.Pitch(z).midi)
                    pcs = sorted({pitch.Pitch(z).pitchClass for z in ps})
                    segs.append(f"@{o}: {','.join(ps)} [{chord.Chord(pcs).pitchedCommonName}]")
                if segs:
                    out.append(f'  m{m.number:>2} ' + '  |  '.join(segs))

    os.makedirs(os.path.join(HERE, 'work'), exist_ok=True)
    rp = os.path.join(HERE, 'work', f's{a.song:02d}_pass.txt')
    with open(rp, 'w') as fh:
        fh.write('\n'.join(out) + '\n')

    print(f"song {a.song} {row['title']}  (book p{row['book_pages']} / "
          f"PDF p{row['pdf_pages']})")
    for d in digest:
        print('  ' + d)
    print(f'  page total: {piece_bar} spans with content'
          + (f'   OMR: {omr_bars} measures'
             f"   {'RECONCILES' if omr_bars == piece_bar else 'MISMATCH -- one of the wide spans hides a barline, or a span is clef/keysig only'}"
             if omr_bars else ''))
    print(f'  report: work/s{a.song:02d}_pass.txt  ({len(out)} lines)')


if __name__ == '__main__':
    main()
