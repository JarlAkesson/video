#!/usr/bin/env python3
"""Render a staff band as stacked x-slices with a pitch ruler drawn on each.

read_staff.py cannot see hollow noteheads and merges the stacked heads of a
two-voice staff, so several of this book's pitches have to be read by eye.  Read
by eye off a bare crop, though, and the answer depends on counting staff lines
in a picture whose bottom line may be cut off -- which is how song 11 bar 5 got
read three different ways.  This draws the answer key: every staff position from
`pad` half-spaces below to `pad` above, at the line spacing staff_comb measured,
labelled with its note name, so reading a pitch is reading the label beside the
notehead.

The band is sliced into `--n` x-windows stacked vertically (the pages are
landscape, so one full-width strip renders at ~5:1 and the labels crush
together); slices overlap so a notehead on a seam is whole in one of them.

usage: pitchruler.py PAGE SYS [--staves 3] [--staff 0] [--x 0.09,0.95] [--n 3]
                     [--dpi 1200] [--clef treble] [--pad 6] -o out.png
"""
import argparse, fitz
from PIL import Image, ImageDraw, ImageFont
import sys
sys.path.insert(0, __import__('os').path.dirname(
    __import__('os').path.abspath(__file__)))
import staff_comb

SRC = "/Users/User/Documents/GitHub/video/MaiSTRO - Claude/Alice_Tegnér_Sjung_med_oss_mamma_8_song_piano.pdf"
TREBLE = ['F5', 'E5', 'D5', 'C5', 'B4', 'A4', 'G4', 'F4', 'E4']
BASS = ['A3', 'G3', 'F3', 'E3', 'D3', 'C3', 'B2', 'A2', 'G2']
SCALE = 'CDEFGAB'


def extend(names, pad):
    def step(nm, d):
        i = SCALE.index(nm[0]) + d
        return SCALE[i % 7] + str(int(nm[1:]) + i // 7)
    return ([step(names[0], k) for k in range(pad, 0, -1)] + list(names)
            + [step(names[-1], -k) for k in range(1, pad + 1)])


ap = argparse.ArgumentParser()
ap.add_argument('page', type=int)
ap.add_argument('sys', type=int)
ap.add_argument('--staves', type=int, default=3)
ap.add_argument('--staff', type=int, default=0)
ap.add_argument('--x', default='0.09,0.95')
ap.add_argument('--n', type=int, default=3)
ap.add_argument('--olap', type=float, default=0.008)
ap.add_argument('--dpi', type=int, default=1200)
ap.add_argument('--clef', default='treble')
ap.add_argument('--pad', type=int, default=6)
ap.add_argument('-o', '--out', required=True)
a = ap.parse_args()

st, H, _thr = staff_comb.systems(a.page, per=a.staves)
lines = st[(a.sys - 1) * a.staves + a.staff]
half = (lines[-1] - lines[0]) / 8.0
names = extend(TREBLE if a.clef == 'treble' else BASS, a.pad)
rows = [(lines[0] - a.pad * half) + i * half for i in range(len(names))]
y0, y1 = (rows[0] - 2 * half) / H, (rows[-1] + 2 * half) / H

x0, x1 = [float(v) for v in a.x.split(',')]
w = (x1 - x0) / a.n
d = fitz.open(SRC); p = d[a.page - 1]; r = p.rect
tiles = []
for i in range(a.n):
    lo = x0 + i * w - (a.olap if i else 0)
    hi = x0 + (i + 1) * w + (a.olap if i < a.n - 1 else 0)
    clip = fitz.Rect(r.x0 + lo * r.width, r.y0 + y0 * r.height,
                     r.x0 + hi * r.width, r.y0 + y1 * r.height)
    pm = p.get_pixmap(dpi=a.dpi, clip=clip)
    tiles.append((Image.frombytes('RGB' if pm.n == 3 else 'RGBA',
                                  (pm.width, pm.height), pm.samples).convert('RGB'),
                  lo, hi))
GUT, SEP = 110, 16
W = GUT + max(t[0].width for t in tiles)
Ht = sum(t[0].height for t in tiles) + SEP * (a.n - 1)
out = Image.new('RGB', (W, Ht), (255, 255, 255))
dr = ImageDraw.Draw(out)
try:
    font = ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf', 46)
except OSError:
    font = ImageFont.load_default()
y = 0
for im, lo, hi in tiles:
    out.paste(im, (GUT, y))
    for nm, ry in zip(names, rows):
        yy = y + (ry / H - y0) / (y1 - y0) * im.height
        on = lines[0] - 0.5 * half <= ry <= lines[-1] + 0.5 * half
        col = (0, 130, 255) if on else (255, 60, 60)
        dr.line([(GUT, yy), (W, yy)], fill=col, width=2)
        dr.text((4, yy - 24), nm, fill=col, font=font)
    y += im.height
    if y < Ht:
        dr.rectangle([0, y, W, y + SEP], fill=(30, 30, 30)); y += SEP
out.save(a.out)
print(a.out, out.size, 'slices:',
      ' '.join(f'{lo:.3f}-{hi:.3f}' for _i, lo, hi in tiles))
