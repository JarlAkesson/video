#!/usr/bin/env python3
"""Count the noteheads on the page and compare with the ones in the file.

Every other check in this skill validates the notes that ARE in the
transcription. None of them can see a note that is missing: if an OMR pass
swallows a note and gives its time to the note before it, the bar still sums
to its meter, the rhythm still looks ordinary, and every note present is
correct. The only thing that changed is how many there are.

So count them. A difference means something is wrong -- always. Which side is
at fault still needs the scan, but the count is what tells you to go and look.

This was written after four such notes were missed across two songs while a
pitch check reported "37 of 37 aligned, 0 issues" -- against a scan that had
found 40 noteheads. The three extra were not noise; two were the dropped
notes. Surplus detections must be explained, never assumed spurious.

Counting caveats, all of which mean "go look", not "ignore":
  * accents, dynamics and the key signature can read as noteheads, inflating
    the page count -- usually by one or two per system
  * hollow noteheads (half and whole notes) and notes on ledger lines below
    the staff are under-detected, deflating it
  * grace notes count on the page and usually not in the file

Examples
--------
  notehead_census.py song.musicxml book.pdf --pages 11-12
  notehead_census.py song.musicxml book.pdf --pages 13 --per-system
"""

import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import read_staff as rs  # noqa: E402


def page_grey(path, page, dpi):
    import fitz
    doc = fitz.open(path)
    pg = doc[page - 1]
    pix = pg.get_pixmap(dpi=dpi)
    from PIL import Image
    return np.array(Image.frombytes('RGB', (pix.width, pix.height), pix.samples).convert('L'))


def staves(path, page, dpi=250, thr=0.70):
    """(y0, y1) page fractions of every five-line staff, top to bottom.

    Lines are clustered by gap size rather than taken five at a time: one faint
    line would otherwise split a staff in two and shift every staff after it.
    """
    a = page_grey(path, page, dpi)
    dark = a < 150
    H, W = dark.shape
    band = dark[:, int(W * 0.20):int(W * 0.80)]      # staves stop short of the margins
    rows = band.sum(axis=1)
    w = band.shape[1]
    cand = [i for i, v in enumerate(rows) if v > thr * w]
    groups = []
    for i in cand:
        if groups and i - groups[-1][-1] <= max(2, H // 600):
            groups[-1].append(i)
        else:
            groups.append([i])
    cs = [sum(g) / len(g) for g in groups]
    if len(cs) < 5:
        return []
    d = np.diff(cs)
    sp = np.median([x for x in d if x < np.median(d) * 2]) if len(d) > 1 else d[0]
    clusters, cur_c = [], [cs[0]]
    for prev, cur in zip(cs, cs[1:]):
        if cur - prev <= sp * 3.0:
            cur_c.append(cur)
        else:
            clusters.append(cur_c)
            cur_c = [cur]
    clusters.append(cur_c)
    return [(c[0] / H, c[-1] / H) for c in clusters if (c[-1] - c[0]) > sp * 3]


def vocal_staves(path, page):
    """Top staff of each system.

    A system here is vocal + piano treble + piano bass, so the staff count must
    be a multiple of three. The ink threshold is swept until it is, because one
    missed staff silently shifts which staff is taken to be the vocal line.
    """
    for thr in (0.70, 0.62, 0.55, 0.48, 0.80, 0.42):
        st = staves(path, page, thr=thr)
        if st and len(st) % 3 == 0:
            return st[::3], thr
    st = staves(path, page)
    return (st[:1] if st else []), None


def count_on(path, page, y0, y1, dpi=700, x0=0.135, x1=0.97):
    h = y1 - y0
    region = [x0, max(0.0, y0 - h * 0.35), x1, min(1.0, y1 + h * 0.35)]
    a = rs.load(path, page, region, dpi)
    dark = a < 130
    fits, err = rs.staff_lines(dark)
    if err:
        return None, err
    W = dark.shape[1]
    y_at = lambda f, x: f[0] * x + f[1]                                  # noqa: E731
    space = (y_at(fits[-1], W // 2) - y_at(fits[0], W // 2)) / 4
    clean = rs.strip_lines(dark, fits, space)
    k = max(1, int(round(space * 0.27)))
    head = rs.erode(clean, k, 1) & rs.erode(clean, k, 0)
    n = 0
    for ymin, ymax, xmin, xmax, _area in rs.components(head):
        w, hh = (xmax - xmin + 1) / space, (ymax - ymin + 1) / space
        if 0.40 <= w <= 1.45 and 0.30 <= hh <= 1.25:
            n += 1
    return n, None


def file_notes(path):
    import music21 as m21
    part = m21.converter.parse(path).parts[0]
    per, total = [], 0
    for mm in part.getElementsByClass('Measure'):
        c = sum(1 for n in mm.notesAndRests if not n.isRest)
        per.append((mm.number, c))
        total += c
    return total, per


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('score', help='the transcription (.musicxml/.mxl)')
    ap.add_argument('pdf', help='the scanned source')
    ap.add_argument('--pages', required=True, help='page or range, e.g. 11-12')
    ap.add_argument('--dpi', type=int, default=700)
    ap.add_argument('--per-system', action='store_true', help='list every system')
    args = ap.parse_args()

    lo, _, hi = args.pages.partition('-')
    pages = range(int(lo), int(hi or lo) + 1)

    total, _per = file_notes(args.score)
    scanned, rows = 0, []
    for pg in pages:
        vs, _thr = vocal_staves(args.pdf, pg)
        if not vs:
            rows.append((pg, None, 'no staff found'))
            continue
        for i, (y0, y1) in enumerate(vs, 1):
            n, err = count_on(args.pdf, pg, y0, y1, args.dpi)
            rows.append((pg, i, err if err else n))
            if not err:
                scanned += n

    if args.per_system:
        for pg, i, n in rows:
            print(f'  page {pg} system {i}: {n}')
    name = os.path.basename(args.score)
    diff = scanned - total
    print(f'{name}: file has {total} notes, page shows {scanned} noteheads, '
          f'difference {diff:+d}')
    if diff == 0:
        print('  counts agree')
        return 0
    if diff > 0:
        print(f'  {diff} more on the page than in the file -- SOMETHING IS WRONG.')
        print('  Most likely notes are missing from the transcription, swallowed into a')
        print('  neighbour (the bar still sums correctly, so no other check sees it).')
        print('  Accents, dynamics and the key signature can also read as noteheads;')
        print('  each surplus has to be explained against the scan, not assumed spurious.')
    else:
        print(f'  {-diff} fewer on the page than in the file -- SOMETHING IS WRONG.')
        print('  Either the file has invented notes, or detection missed some: hollow')
        print('  half/whole noteheads and notes on ledger lines below the staff are the')
        print('  usual under-counts. Check those bars against the scan.')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
