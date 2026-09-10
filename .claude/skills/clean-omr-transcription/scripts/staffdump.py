#!/usr/bin/env python3
"""Barline candidates for one staff, as page fractions.

A barline is a column of dark pixels spanning the WHOLE staff height.  So is a
beamed stem, which is why coverage alone is not enough -- book 6 lost an hour
to a song 11 sixteenth-note beam that cleared the test.  Two extra measurements
are returned with each candidate so a borderline column can be judged rather
than guessed: `clean` is the coverage a staff-height away on either side (a
barline stands alone, a stem has its notehead beside it) and `mrg` is the ink
just above and below the staff (a barline drawn through a system continues into
the margin, a stem stops).

Discriminating the stems is left to the CALLER, because the caller knows where
the noteheads are and can simply exclude their x positions -- which is what
songpass.py does, and it is far more reliable than any threshold here.  That is
also why this no longer has a CLI: on its own the raw candidate list needs a
human to guess which entries are real, and guessing was the cost it existed to
remove.
"""
import sys

import numpy as np, fitz
sys.path.insert(0, __import__('os').path.dirname(
    __import__('os').path.abspath(__file__)))
from staff_comb import systems, SRC

RS = "/Users/User/Documents/GitHub/video/.claude/skills/clean-omr-transcription/scripts/read_staff.py"


def bar_candidates(pno, lines, h, x0, x1, dpi=600, cover=0.90):
    """Columns of one staff that read as a barline. Returns (frac, cov, clean, mrg)."""
    top, bot = lines[0] / h, lines[-1] / h
    d = fitz.open(SRC); p = d[pno - 1]; r = p.rect
    pad = 1.5 * (bot - top) / 4.0
    clip = fitz.Rect(r.x0 + x0 * r.width, r.y0 + (top - pad) * r.height,
                     r.x0 + x1 * r.width, r.y0 + (bot + pad) * r.height)
    pm = p.get_pixmap(dpi=dpi, clip=clip)
    im = np.frombuffer(pm.samples, np.uint8).reshape(pm.height, pm.width, pm.n)
    g = im[:, :, :3].mean(axis=2)
    mpx = int(round(pm.height * pad / (bot - top + 2 * pad)))
    inner = g[mpx:pm.height - mpx, :]
    cov = (inner < 140).mean(axis=0)
    mrg = np.maximum((g[:mpx, :] < 140).mean(axis=0), (g[pm.height - mpx:, :] < 140).mean(axis=0))
    sh = pm.height - 2 * mpx
    w = max(2, int(round(sh / 4.0 * 0.9)))
    padc = np.pad(cov, w, constant_values=0.0)
    clean = np.minimum(padc[0:len(cov)], padc[2 * w:len(cov) + 2 * w])
    hits = np.where(cov > cover)[0]
    groups, cur = [], []
    for c in hits:
        if cur and c - cur[-1] > 3:
            groups.append(cur); cur = []
        cur.append(c)
    if cur:
        groups.append(cur)
    out = []
    for gp in groups:
        c = float(np.mean(gp))
        out.append((x0 + (c / pm.width) * (x1 - x0), cov[gp].max(),
                    clean[gp].min(), mrg[gp].min()))
    return out
