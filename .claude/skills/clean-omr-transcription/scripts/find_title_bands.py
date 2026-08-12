#!/usr/bin/env python3
"""Locate the bands where song titles sit in a scanned songbook PDF.

A song runs from its own numbered title to just before the next one, so a
page-range split of a book is only safe if no song starts mid-page. This script
finds every candidate title band mechanically; READING the titles still needs
eyes, because a scanned PDF has no text layer and the .omr usually carries no
OCR either.

How it works: threshold each page, treat rows whose dark-pixel count exceeds
--ink-threshold of the page width as staff lines, cluster them into staves, and
crop the whitespace band above each system. Crops are stacked into a handful of
composite images so a whole book can be read in a few looks instead of one page
at a time.

Output
------
  <out>/titles_N.png   composites to read
  <out>/bands.json     per page: staff spans, band rects, top_of_page flag,
                       has_staves
  stdout               summary: pages with no staves (text-only verse pages,
                       which must be excluded from sheet ranges) and how many
                       candidate bands are NOT at the top of their page --
                       those are the mid-page song starts that make a
                       page-range split unsafe.

Example
-------
  find_title_bands.py book.pdf --out /tmp/bands --first-page 4
"""

import argparse
import json
import os
import sys


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('pdf')
    ap.add_argument('--out', required=True, help='directory for composites + bands.json')
    ap.add_argument('--first-page', type=int, default=1, help='1-based, inclusive')
    ap.add_argument('--last-page', type=int, default=0, help='1-based, inclusive; 0 = last')
    ap.add_argument('--scale', type=float, default=0.55, help='render scale (default 0.55)')
    ap.add_argument('--ink-threshold', type=float, default=0.35,
                    help='fraction of page width that makes a row a staff line')
    ap.add_argument('--staff-gap', type=int, default=25, help='row gap that separates staves')
    ap.add_argument('--system-gap', type=int, default=130,
                    help='vertical gap above a system big enough to hold a title')
    ap.add_argument('--per-composite', type=int, default=9, help='bands per composite image')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()

    try:
        import fitz
        import numpy as np
        from PIL import Image, ImageDraw
    except ImportError as e:
        sys.exit(f'needs PyMuPDF, numpy and Pillow: {e}')

    os.makedirs(args.out, exist_ok=True)
    doc = fitz.open(args.pdf)
    last = args.last_page or doc.page_count
    bands, meta = [], {}

    for pno in range(args.first_page - 1, min(last, doc.page_count)):
        pix = doc[pno].get_pixmap(matrix=fitz.Matrix(args.scale, args.scale),
                                  colorspace=fitz.csGRAY)
        arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
        img = Image.fromarray(arr)
        rows = (arr < 128).sum(1)
        idx = np.where(rows > pix.width * args.ink_threshold)[0]

        staves = []
        if len(idx):
            start = prev = idx[0]
            for r in idx[1:]:
                if r - prev > args.staff_gap:
                    staves.append((int(start), int(prev)))
                    start = r
                prev = r
            staves.append((int(start), int(prev)))
        staves = [t for t in staves if t[1] - t[0] >= 15]

        if not staves:
            meta[pno + 1] = {'has_staves': False, 'staves': [], 'bands': []}
            continue

        cands = [(max(0, staves[0][0] - 150), staves[0][0], True)]
        for k in range(len(staves) - 1):
            gap = staves[k + 1][0] - staves[k][1]
            if gap > args.system_gap:
                cands.append((staves[k][1] + int(gap * 0.15), staves[k + 1][0], False))

        meta[pno + 1] = {
            'has_staves': True,
            'staves': staves,
            'bands': [{'y0': a, 'y1': b, 'top_of_page': t} for a, b, t in cands],
        }
        for (y0, y1, top) in cands:
            bands.append((pno + 1, y0, top, img.crop((0, y0, pix.width, y1))))

    width = max((b[3].width for b in bands), default=1)
    composites = []
    for gi in range(0, len(bands), args.per_composite):
        group = bands[gi:gi + args.per_composite]
        height = sum(b[3].height + 26 for b in group)
        canvas = Image.new('L', (width, height), 255)
        draw = ImageDraw.Draw(canvas)
        y = 0
        for (pg, y0, top, crop) in group:
            draw.text((6, y + 6), f'PDF page {pg}  y={y0}  {"TOP" if top else "MID-PAGE"}', fill=0)
            y += 26
            canvas.paste(crop, (0, y))
            y += crop.height
        path = os.path.join(args.out, f'titles_{gi // args.per_composite}.png')
        canvas.resize((int(width * 0.62), int(height * 0.62))).save(path)
        composites.append(path)

    with open(os.path.join(args.out, 'bands.json'), 'w') as fh:
        json.dump(meta, fh, indent=2)

    no_staves = sorted(p for p, m in meta.items() if not m['has_staves'])
    midpage = [(p, b['y0']) for p, m in meta.items() for b in m['bands'] if not b['top_of_page']]

    if args.json:
        print(json.dumps({'composites': composites, 'pages_without_staves': no_staves,
                          'mid_page_bands': midpage}, indent=2))
        return 0
    print(f'{len(bands)} candidate band(s) across {len(meta)} page(s)')
    print(f'composites: {len(composites)} -> {args.out}/titles_*.png  (read these)')
    print(f'pages with no staves (exclude from sheet ranges): {no_staves or "none"}')
    print(f'mid-page bands: {len(midpage)}'
          + ('  <- a page-range split may be UNSAFE; check these' if midpage else
             '  -> every band is at a page top, so a page-range split is safe'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
