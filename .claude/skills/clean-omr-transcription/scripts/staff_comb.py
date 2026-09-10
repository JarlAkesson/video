#!/usr/bin/env python3
"""Find every staff on a page with a 5-line comb, not a darkness threshold.

The approach this replaced thresholded the per-row dark fraction (staff_bands.py,
retired).  On book 8 that misses
staves outright: the scan fades toward the foot of pages 18, 25 and 28, so at
dark>0.45 those pages report 5, 4 and 2 staves instead of 6, and no single
threshold fixes all three without inventing staves elsewhere (0.35 turns page
11 into 8 staves).

A staff is not "5 dark rows" -- it is five EQUALLY SPACED dark rows.  So the
profile is scored against a comb of 5 lines at the book's own line spacing and
the maxima are taken: a faint staff still beats its neighbourhood, and lyrics,
beams and slurs never line up at exactly 5 x sp.  Spacing is measured from the
page itself (the strongest gap between adjacent dark rows), so it needs no
per-page tuning.

usage: staff_comb.py 5 6 7 ...
"""
import os, sys

import numpy as np, fitz

# The book being read.  OMR_SRC overrides it, which is how this gets pointed at
# the next book without editing anything; the fallback is simply whichever book
# was in hand when the module was written.
SRC = os.environ.get('OMR_SRC') or (
    "/Users/User/Documents/GitHub/video/MaiSTRO - Claude/"
    "Alice_Tegnér_Sjung_med_oss_mamma_8_song_piano.pdf")


def profile(pno, dpi=200, x0=0.12, x1=0.88):
    d = fitz.open(SRC); p = d[pno - 1]; r = p.rect
    clip = fitz.Rect(r.x0 + x0 * r.width, r.y0, r.x0 + x1 * r.width, r.y1)
    pm = p.get_pixmap(dpi=dpi, clip=clip)
    a = np.frombuffer(pm.samples, np.uint8).reshape(pm.height, pm.width, pm.n)
    return (a[:, :, :3].mean(axis=2) < 150).mean(axis=1), pm.height


def spacing(prof):
    # candidate lines at a permissive threshold, then the modal adjacent gap
    rows = np.where(prof > 0.30)[0]
    lines, cur = [], [rows[0]]
    for y in rows[1:]:
        if y - cur[-1] <= 2:
            cur.append(y)
        else:
            lines.append(np.mean(cur)); cur = [y]
    lines.append(np.mean(cur))
    gaps = np.diff(lines)
    gaps = gaps[(gaps > 4) & (gaps < 40)]
    hist, edges = np.histogram(gaps, bins=np.arange(4, 41, 1))
    return float(edges[hist.argmax()]) + 0.5


def staves(pno, dpi=200, x0=0.12, x1=0.88, thr=0.40):
    prof, h = profile(pno, dpi, x0, x1)
    sp = spacing(prof)
    span = int(round(4 * sp))
    # comb score at every start row
    idx = np.arange(len(prof) - span)
    off = np.round(np.arange(5) * sp).astype(int)
    score = np.zeros(len(idx))
    for o in off:
        score += prof[idx + o]
    score /= 5.0
    # non-maximum suppression: staves cannot overlap
    # the scan's black page border scores like a staff, so ignore the outer 5%
    lo, hi = int(0.06 * len(prof)), int(0.92 * len(prof))
    order = np.argsort(-score)
    taken = []
    for i in order:
        if score[i] < thr:
            break
        if not (lo <= i <= hi):
            continue
        if any(abs(i - t) < span for t in taken):
            continue
        taken.append(i)
    out = []
    for t in sorted(taken):
        # refine each of the 5 lines to the local darkness peak
        ls = []
        for o in off:
            w = prof[max(0, t + o - 2):t + o + 3]
            ls.append(float(max(0, t + o - 2) + w.argmax()))
        out.append(ls)
    return out, h


def systems(pno, per=3, dpi=200, x0=0.12, x1=0.88):
    """staves() with the comb threshold chosen so the count divides by `per`.

    No single threshold works for the whole book: 0.40 finds 6 staves on 22 of
    the 25 music pages but only 5 on page 25 and 3 on page 28, while 0.30 finds
    page 25 and turns page 5 into 7.  The number of staves per system is known
    (3 for the piano songs, 2 for the two choral ones), so it is used as the
    check: the loosest threshold that still yields a whole number of systems.
    """
    best = None
    for thr in (0.44, 0.40, 0.36, 0.32, 0.28, 0.24, 0.20):
        st, h = staves(pno, dpi, x0, x1, thr)
        if len(st) >= per and len(st) % per == 0:
            return st, h, thr
        if best is None or len(st) > len(best[0]):
            best = (st, h, thr)
    return best[0], best[1], best[2]


if __name__ == '__main__':
    for pno in [int(x) for x in sys.argv[1:]]:
        st, h = staves(pno)
        print(f"page {pno}: {len(st)} staves")
        prev = None
        for i, s in enumerate(st):
            top, bot = s[0] / h, s[-1] / h
            gap = '' if prev is None else f" gap={top - prev:.4f}"
            print(f"  {i}: top={top:.4f} bot={bot:.4f} space={(s[-1]-s[0])/4/h:.4f}{gap}")
            prev = bot
