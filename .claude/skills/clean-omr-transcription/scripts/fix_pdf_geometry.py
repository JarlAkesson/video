#!/usr/bin/env python3
"""Report or repair the page geometry of a scanned-music PDF before OMR.

Audiveris rasterizes from a PDF's DECLARED physical page size, not from the
embedded image's pixel count. A scan whose declared size is far larger than the
image warrants forces Audiveris to upsample internally, which produces blur,
slow processing and per-step timeouts -- and looks exactly like "the OMR engine
is bad at this piece".

--report prints the current geometry and the implied px/pt so the problem is
visible before anything is rewritten. Without it, the PDF is rebuilt at a sane
page size (image pixels / --px-per-pt) and, optionally, its images upsampled
toward --max-pixels, which measurably improves recognition even though it adds
no new information.

Never raise Audiveris's maxPixelCount to allow true native resolution instead:
very large images hit a hardcoded per-step timeout regardless of the pixel cap.

Examples
--------
  fix_pdf_geometry.py book.pdf --report
  fix_pdf_geometry.py book.pdf -o book_fixed.pdf
  fix_pdf_geometry.py book.pdf -o book_fixed.pdf --upsample --pages 4-5
"""

import argparse
import sys


def parse_pages(spec, total):
    if not spec:
        return list(range(total))
    out = []
    for part in spec.split(','):
        if '-' in part:
            a, b = part.split('-')
            out += list(range(int(a) - 1, int(b)))
        else:
            out.append(int(part) - 1)
    return [p for p in out if 0 <= p < total]


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('pdf')
    ap.add_argument('-o', '--output', help='rebuilt PDF (omit with --report)')
    ap.add_argument('--report', action='store_true', help='print geometry, write nothing')
    ap.add_argument('--px-per-pt', type=float, default=4.12,
                    help='target pixels per point (default 4.12, derived empirically '
                         'from a known-good page; re-derive it for a new scanner)')
    ap.add_argument('--upsample', action='store_true',
                    help='also enlarge embedded images toward --max-pixels')
    ap.add_argument('--max-pixels', type=int, default=18_000_000,
                    help="stay under Audiveris's 20M cap (default 18M)")
    ap.add_argument('--pages', help='1-based list/ranges, e.g. 4-5,9')
    args = ap.parse_args()

    try:
        import fitz
    except ImportError as e:
        sys.exit(f'needs PyMuPDF: {e}')

    doc = fitz.open(args.pdf)
    pages = parse_pages(args.pages, doc.page_count)

    if args.report:
        print(f'{"page":>5} {"declared pt":>16} {"image px":>16} {"px/pt":>7}  verdict')
        for pno in pages:
            page = doc[pno]
            r = page.rect
            imgs = page.get_images(full=True)
            if not imgs:
                print(f'{pno + 1:5d} {r.width:7.0f}x{r.height:<8.0f} {"(no image)":>16}')
                continue
            w, h = imgs[0][2], imgs[0][3]
            ratio = w / r.width if r.width else 0
            verdict = 'ok' if abs(ratio - args.px_per_pt) < args.px_per_pt * 0.35 else \
                      'REBUILD: Audiveris will upsample internally'
            print(f'{pno + 1:5d} {r.width:7.0f}x{r.height:<8.0f} {w:7d}x{h:<8d} {ratio:7.2f}  {verdict}')
        return 0

    if not args.output:
        ap.error('give -o OUTPUT, or use --report')

    out = fitz.open()
    for pno in pages:
        page = doc[pno]
        pix = page.get_pixmap(matrix=fitz.Matrix(1, 1))
        w, h = pix.width, pix.height
        if args.upsample and w * h < args.max_pixels:
            factor = min((args.max_pixels / float(w * h)) ** 0.5, 4.0)
            pix = page.get_pixmap(matrix=fitz.Matrix(factor, factor))
            w, h = pix.width, pix.height
        pw, ph = w / args.px_per_pt, h / args.px_per_pt
        new = out.new_page(width=pw, height=ph)
        new.insert_image(fitz.Rect(0, 0, pw, ph), stream=pix.tobytes('png'))
    out.save(args.output)
    print(f'wrote {args.output}: {len(pages)} page(s) at {args.px_per_pt} px/pt'
          + (f', upsampled toward {args.max_pixels:,} px' if args.upsample else ''))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
