#!/usr/bin/env python3
"""Locate the melody staff of every system, and optionally crop it onto its own page.

Cropping the melody out is worth reaching for whenever the job is melody-only.
Left in place, the accompaniment staves are what scramble part assignment: a
grand staff below the vocal line makes Audiveris hand measures to the wrong
part, silently drop a page, or die outright (one page of a book here failed with
"Denominator is zero" at every resolution and transcribed cleanly once the piano
was gone). A lone staff has none of those failure modes.

Two things the staff finder has to get right, both learned from getting them
wrong:

  * The ink threshold is SWEPT, not fixed. A faint page drops below any single
    cutoff and silently yields a four-line staff, which shifts every staff after
    it. Cutoffs are scored on whether every group comes out with exactly five.

  * The row profile is taken over a NARROW COLUMN. Scans skew, and across the
    full width a staff line drifts far enough that no row is dark end to end --
    which is why two pages here looked blank.

Staves are grouped into systems of `--per-system` (default 3: melody plus a
piano grand staff); the melody is the first staff of each group.

Examples
--------
  melody_staves.py book.pdf --pages 4-9            # report what it found
  melody_staves.py book.pdf --pages 15,16,17 -o mel.pdf
"""

import argparse
import sys

import fitz
import numpy as np

DPI = 150
FRACS = (0.40, 0.32, 0.50, 0.25, 0.60, 0.20, 0.15, 0.70)


def _rows(doc, pg, x0=0.12, x1=0.45):
    pix = doc[pg - 1].get_pixmap(dpi=DPI)
    a = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, 0]
    sl = a[:, int(a.shape[1] * x0):int(a.shape[1] * x1)]
    return (sl < 130).sum(axis=1), sl.shape[1], pix.height


def _group(rows, thr, gap=70):
    out, inb, st = [], False, 0
    for i, v in enumerate(rows):
        if v > thr and not inb:
            st, inb = i, True
        elif v <= thr and inb:
            out.append((st + i - 1) // 2)
            inb = False
    if not out:
        return []
    groups, cur = [], [out[0]]
    for prev, y in zip(out, out[1:]):
        if y - prev <= gap:
            cur.append(y)
        else:
            groups.append(cur)
            cur = [y]
    groups.append(cur)
    return [(g[0], g[-1], len(g)) for g in groups]


def page_staves(doc, pg, per_system=3):
    """[(top, bottom, line_count)] for every staff on the page, top to bottom."""
    rows, W, H = _rows(doc, pg)
    best = None
    for f in FRACS:
        g = _group(rows, f * W)
        if not g:
            continue
        if all(s[2] == 5 for s in g) and len(g) % per_system == 0:
            return g, H
        score = (sum(1 for s in g if s[2] != 5), -len(g))
        if best is None or score < best[1]:
            best = (g, score)
    return (best[0] if best else []), H


def melody_staves(doc, pg, per_system=3):
    """[(top, bottom)] for the melody staff of each system, in 150dpi rows."""
    st, H = page_staves(doc, pg, per_system)
    return [s[:2] for s in st[::per_system]], H


def build(doc, pages, out, per_system=3, dpi=200, pad_top=140, pad_bot=105,
          per_page=1, px_per_pt=4.12):
    """Write a PDF holding only the melody staves of `pages`.

    One system per page by default: stacking several onto one page invites
    Audiveris to read them as a grand staff and octave-shift the lower ones.
    The default dpi is deliberately modest -- these scans are ~3200px wide, so
    200dpi is already heavy upsampling, and Audiveris refuses images over 20M
    pixels.
    """
    strips = []
    for pg in pages:
        mel, H = melody_staves(doc, pg, per_system)
        p = doc[pg - 1]
        r = p.rect
        for top, bot in mel:
            clip = fitz.Rect(r.x0, r.y0 + r.height * (top - pad_top) / H,
                             r.x1, r.y0 + r.height * (bot + pad_bot) / H)
            strips.append(p.get_pixmap(dpi=dpi, clip=clip))
    new = fitz.open()
    for i in range(0, len(strips), per_page):
        chunk = strips[i:i + per_page]
        page = new.new_page(width=max(s.width for s in chunk) / px_per_pt,
                            height=sum(s.height for s in chunk) / px_per_pt)
        y = 0.0
        for s in chunk:
            page.insert_image(fitz.Rect(0, y, s.width / px_per_pt,
                                        y + s.height / px_per_pt), pixmap=s)
            y += s.height / px_per_pt
    new.save(out)
    print(f'{out}: {len(strips)} strip(s) -> {len(new)} page(s)')


def parse_pages(spec):
    out = []
    for part in spec.split(','):
        if '-' in part:
            a, b = part.split('-')
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('pdf')
    ap.add_argument('--pages', required=True, help='e.g. 4-9 or 15,16,17')
    ap.add_argument('--per-system', type=int, default=3,
                    help='staves per system (default 3: melody + grand staff)')
    ap.add_argument('-o', '--out', help='write a melody-only PDF here')
    ap.add_argument('--dpi', type=int, default=200)
    ap.add_argument('--per-page', type=int, default=1)
    args = ap.parse_args()

    doc = fitz.open(args.pdf)
    pages = parse_pages(args.pages)
    if args.out:
        build(doc, pages, args.out, args.per_system, args.dpi, per_page=args.per_page)
        return 0
    bad = 0
    for pg in pages:
        st, H = page_staves(doc, pg, args.per_system)
        odd = [s for s in st if s[2] != 5]
        bad += len(odd)
        print(f'p{pg}: {len(st)} staves, melody at '
              f'{[s[:2] for s in st[::args.per_system]]}'
              + (f'   NOT FIVE LINES: {odd}' if odd else ''))
    return 1 if bad else 0


if __name__ == '__main__':
    raise SystemExit(main())
