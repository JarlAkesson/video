#!/usr/bin/env python3
"""Measure BOTH notes of every dyad on a staff engraved in two parts.

`read_staff.py` rejects a dyad outright, and silently: two noteheads a third
apart touch, forming a blob about 1.4 staff spaces tall, which fails the height
test that exists to throw out beams. On a duet staff that means most of the
music simply does not appear -- not as an error, just as absent notes.

Here a tall-but-narrow blob is kept and split, its top and bottom halves read as
one notehead each, while genuinely wide blobs (beams) are still discarded.
Detections sharing an x are printed as one stack, highest first, so the upper
and lower parts can be read off directly.

Everything `read_staff.py` says still applies: this reads pitch, not rhythm, and
below ~60px per staff space it should not be trusted. A stack of one is a place
where the two parts meet in unison, or where only one of them sings -- the scan
settles which.

Examples
--------
  read_dyads.py book.pdf --page 28 --system 0 --key 1
  read_dyads.py book.pdf --page 28 --system 0 --key 1 --x 0.60,0.99
"""

import argparse
import os
import sys

import fitz
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import read_staff as RS
from melody_staves import melody_staves


def stacks(doc, pg, top, bot, H, key, x0, x1, dpi=700, pad=75):
    p = doc[pg - 1]
    r = p.rect
    clip = fitz.Rect(r.x0 + r.width * x0, r.y0 + r.height * (top - pad) / H,
                     r.x0 + r.width * x1, r.y0 + r.height * (bot + pad) / H)
    pix = p.get_pixmap(dpi=dpi, clip=clip)
    a = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, 0]
    dark = a < 130
    fits, err = RS.staff_lines(dark)
    if err:
        return None, None, err
    W = dark.shape[1]
    y_at = lambda f, x: f[0] * x + f[1]
    space = (y_at(fits[-1], W // 2) - y_at(fits[0], W // 2)) / 4
    clean = RS.strip_lines(dark, fits, space)
    k = max(1, int(round(space * 0.27)))
    head = RS.erode(clean, k, 1) & RS.erode(clean, k, 0)
    hits = []
    for ymin, ymax, xmin, xmax, _area in RS.components(head):
        w = (xmax - xmin + 1) / space
        h = (ymax - ymin + 1) / space
        if not (0.40 <= w <= 1.45):
            continue                       # a beam spans two stems; a head never does
        cx = (xmin + xmax) / 2
        if h <= 1.25:
            ys = [(ymin + ymax) / 2]
        elif h <= 2.6:
            pad_in = space * 0.32          # each head sits its own half-height inside
            ys = [ymin + pad_in, ymax - pad_in]
        else:
            continue
        for cy in ys:
            st = (y_at(fits[-1], cx) - cy) / (space / 2)
            if -9 <= st <= 12:             # nothing sung reaches C6 or A2; text does
                hits.append((cx / W, st))
    hits.sort()
    out, cur = [], []
    for xf, st in hits:
        if cur and xf - cur[-1][0] > (space * 0.85) / W:
            out.append(cur)
            cur = []
        cur.append((xf, st))
    if cur:
        out.append(cur)
    return out, space, None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('pdf')
    ap.add_argument('--page', type=int, required=True)
    ap.add_argument('--system', type=int, default=0, help='0-based system on the page')
    ap.add_argument('--key', type=int, default=0, help='negative flats, positive sharps')
    ap.add_argument('--x', default='0.06,0.99', help='x window as page fractions')
    ap.add_argument('--per-system', type=int, default=3)
    ap.add_argument('--dpi', type=int, default=700)
    ap.add_argument('--clef', choices=('treble', 'bass'), default='treble')
    ap.add_argument('--min-space', type=float, default=60)
    args = ap.parse_args()

    x0, x1 = (float(v) for v in args.x.split(','))
    doc = fitz.open(args.pdf)
    mel, H = melody_staves(doc, args.page, args.per_system)
    if args.system >= len(mel):
        print(f'page {args.page} has {len(mel)} system(s)', file=sys.stderr)
        return 2
    top, bot = mel[args.system]
    out, space, err = stacks(doc, args.page, top, bot, H, args.key, x0, x1, args.dpi)
    if err:
        print(err, file=sys.stderr)
        return 2
    print(f'staff space {space:.1f}px, {len(out)} stack(s)')
    if space < args.min_space:
        print(f'*** {space:.0f}px per space is below {args.min_space:.0f} -- '
              f'RE-RENDER LARGER before trusting any pitch below', file=sys.stderr)
    shaky = 0
    for c in out:
        names, flag = [], ''
        for _, st in sorted(c, key=lambda t: -t[1]):
            names.append(RS.name_of(int(round(st)), args.clef, args.key))
            if abs(st - round(st)) > 0.28:
                flag = '  <-- BETWEEN TWO PITCHES, re-render larger'
        shaky += bool(flag)
        pgx = x0 + c[0][0] * (x1 - x0)
        print(f'  x={pgx:.3f}  {"/".join(names)}{flag}')
    return 1 if shaky else 0


if __name__ == '__main__':
    raise SystemExit(main())
