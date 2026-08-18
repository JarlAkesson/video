#!/usr/bin/env python3
"""Measure the pitch of every notehead in a region of a scanned score.

Reading pitch by eye off a small crop is where transcription goes wrong: at a
glance you compare noteheads to each other ("this one looks a bit higher") and
a third can pass as a second. This reads each notehead against the staff lines
and prints its diatonic step, so pitch becomes a measurement rather than an
impression.

Three things it has to get right, all learned from getting them wrong:

  * Noteheads are CONNECTED to the staff lines running through them, so naive
    blob-finding merges a whole system into one component. They are isolated
    instead by requiring a solid dark run of about half a staff space in BOTH
    directions: stems fail the horizontal test, staff lines and beams fail the
    vertical one, only noteheads pass both.

  * Scans SKEW. Each staff line is fitted as a function of x rather than taken
    as one y, because a global average drifts by a third of a step or more by
    the right-hand end of a system -- enough to turn a G into an A.

  * Resolution decides everything. Below roughly 60px per staff space, pitch is
    not reliably readable no matter how careful the reader is; the script says
    so rather than printing confident nonsense. Rhythm survives much lower.

Every reading prints its FRACTIONAL step. A value near x.5 sits between two
pitches and means "re-render larger", not "round it".

Examples
--------
  read_staff.py score.pdf --page 10 --region 0.70,0.115,0.90,0.205
  read_staff.py score.pdf --page 10 --region 0.1,0.5,0.9,0.6 --dpi 800
  read_staff.py crop.png --clef bass --key -1
"""

import argparse
import os
import sys

import numpy as np
from PIL import Image

LETTERS = 'CDEFGAB'
BOTTOM_LINE = {'treble': 30, 'bass': 18}      # diatonic index of the bottom line
FLAT_ORDER = 'BEADGCF'
SHARP_ORDER = 'FCGDAEB'


def load(path, page, region, dpi):
    """Return a greyscale array for the requested region."""
    if path.lower().endswith('.pdf'):
        import fitz
        doc = fitz.open(path)
        pg = doc[page - 1]
        r = pg.rect
        if region:
            x0, y0, x1, y1 = region
            clip = fitz.Rect(r.x0 + r.width * x0, r.y0 + r.height * y0,
                             r.x0 + r.width * x1, r.y0 + r.height * y1)
        else:
            clip = r
        pix = pg.get_pixmap(dpi=dpi, clip=clip)
        img = Image.frombytes('RGB', (pix.width, pix.height), pix.samples).convert('L')
    else:
        img = Image.open(path).convert('L')
        if region:
            w, h = img.size
            x0, y0, x1, y1 = region
            img = img.crop((int(w * x0), int(h * y0), int(w * x1), int(h * y1)))
    return np.array(img)


def erode(mask, k, axis):
    """True where every pixel within +-k along `axis` is also True.

    Done with a cumulative sum so it stays fast on large renders.
    """
    m = mask if axis == 1 else mask.T
    pad = np.zeros((m.shape[0], k), bool)
    p = np.hstack([pad, m, pad]).astype(np.int32)
    cs = np.cumsum(p, axis=1)
    cs = np.hstack([np.zeros((m.shape[0], 1), np.int32), cs])
    win = cs[:, 2 * k + 1:] - cs[:, :-(2 * k + 1)]
    out = win == (2 * k + 1)
    return out if axis == 1 else out.T


def staff_lines(dark):
    """Fit the five staff lines as y = a*x + b each, tolerating scan skew."""
    H, W = dark.shape
    rows = dark.sum(axis=1)
    cand = [i for i, v in enumerate(rows) if v > 0.55 * W]
    groups = []
    for i in cand:
        if groups and i - groups[-1][-1] <= max(2, H // 200):
            groups[-1].append(i)
        else:
            groups.append([i])
    centres = [sum(g) / len(g) for g in groups]
    if len(centres) < 5:
        return None, f'found {len(centres)} staff line(s), need 5 -- adjust --region'
    if len(centres) > 5:
        # keep the most evenly spaced run of five (hairpins and beams look like lines)
        best, err = None, None
        for s in range(len(centres) - 4):
            five = centres[s:s + 5]
            d = np.diff(five)
            e = d.std() / max(d.mean(), 1e-9)
            if err is None or e < err:
                best, err = five, e
        centres = best
    fits = []
    for cy in centres:
        band = int(max(2, (centres[-1] - centres[0]) / 4 * 0.25))
        xs, ys = [], []
        for x in range(0, W, max(1, W // 200)):
            lo, hi = int(cy - band), int(cy + band) + 1
            col = np.nonzero(dark[max(0, lo):hi, x])[0]
            if len(col):
                xs.append(x)
                ys.append(max(0, lo) + col.mean())
        fits.append(np.polyfit(xs, ys, 1) if len(xs) > 5 else np.array([0.0, cy]))
    return fits, None


def name_of(step, clef, key):
    d = BOTTOM_LINE[clef] + step
    letter = LETTERS[d % 7]
    octave = d // 7
    acc = ''
    if key < 0 and letter in FLAT_ORDER[:abs(key)]:
        acc = '-'
    elif key > 0 and letter in SHARP_ORDER[:key]:
        acc = '#'
    return f'{letter}{acc}{octave}'


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('file', help='.pdf, or an already-cropped image')
    ap.add_argument('--page', type=int, default=1, help='1-based PDF page')
    ap.add_argument('--region', help='x0,y0,x1,y1 as fractions of the page')
    ap.add_argument('--dpi', type=int, default=600, help='render resolution (default 600)')
    ap.add_argument('--clef', choices=('treble', 'bass'), default='treble')
    ap.add_argument('--key', type=int, default=0,
                    help='signature: negative for flats, positive for sharps')
    ap.add_argument('--threshold', type=int, default=130, help='ink cutoff, 0-255')
    ap.add_argument('--min-space', type=float, default=60,
                    help='staff space in px below which pitch is unreliable (default 60)')
    args = ap.parse_args()

    region = [float(v) for v in args.region.split(',')] if args.region else None
    a = load(args.file, args.page, region, args.dpi)
    dark = a < args.threshold

    fits, err = staff_lines(dark)
    if err:
        print(err, file=sys.stderr)
        return 2
    W = dark.shape[1]
    mid = W // 2
    y_at = lambda f, x: f[0] * x + f[1]
    space = (y_at(fits[-1], mid) - y_at(fits[0], mid)) / 4
    skew = abs(y_at(fits[-1], 0) - y_at(fits[-1], W - 1))
    print(f'staff space {space:.1f}px, skew {skew:.1f}px across the region')
    if space < args.min_space:
        print(f'*** {space:.0f}px per space is below {args.min_space:.0f} -- '
              f'RE-RENDER LARGER before trusting any pitch below', file=sys.stderr)

    k = max(1, int(round(space * 0.27)))
    head = erode(dark, k, 1) & erode(dark, k, 0)
    cols = head.sum(axis=0)
    groups, cur = [], None
    for i, v in enumerate(cols):
        if v:
            cur = [i, i] if cur is None else [cur[0], i]
        else:
            if cur and cur[1] - cur[0] >= space * 0.45:
                groups.append(tuple(cur))
            cur = None
    if cur and cur[1] - cur[0] >= space * 0.45:
        groups.append(tuple(cur))

    print(f'{len(groups)} notehead(s)')
    shaky = 0
    for x0, x1 in groups:
        ys, xs = np.nonzero(head[:, x0:x1 + 1])
        cx = x0 + xs.mean()
        step = (y_at(fits[-1], cx) - ys.mean()) / (space / 2)
        frac = abs(step - round(step))
        flag = '  <-- BETWEEN TWO PITCHES, re-render larger' if frac > 0.28 else ''
        if flag:
            shaky += 1
        print(f'  x={cx:7.0f}  step={step:6.2f}  {name_of(int(round(step)), args.clef, args.key)}{flag}')
    return 1 if shaky else 0


if __name__ == '__main__':
    raise SystemExit(main())
