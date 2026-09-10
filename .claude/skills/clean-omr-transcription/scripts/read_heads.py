#!/usr/bin/env python3
"""Measure every notehead in a staff window: pitch, filled/hollow, and dots.

read_staff.py answers "what pitch is this notehead" and answers it well, but it
is blind to the three things that sent book 8's transcription to the image
viewer over and over:

  * HOLLOW noteheads.  Its detector requires a solid dark run of half a staff
    space in both directions, so the thin ring of a half note fails it and the
    note simply does not exist.  Every half and whole note in book 8 had to be
    taken from the OMR and checked by eye -- and the OMR was wrong about song
    11 bar 5, reading the printed G4+E4 as E4 twice.
  * STACKED noteheads.  Songs 11 and 14 are printed duets: two voices share the
    staff and their heads touch.  read_staff either merges them into a centroid
    that is the pitch of neither, or rejects the merged blob on height.
  * AUGMENTATION DOTS.  Audiveris reads this engraving's durations correctly
    except for dots, which it drops -- that one error class is why songs 12, 13
    and 14 each needed a bar-by-bar visual pass.

Holes are used here as a PREPROCESSING step, not as evidence.  An earlier
attempt (readhollow.py, deleted) searched the staff for enclosed white regions
and called each a hollow head; this engraving's eighth-note flags enclose
notehead-sized white areas, so it produced twenty false positives for three
real half notes.  Here the holes are filled first so a ring becomes a solid
disc the ordinary detector can find, and the shape test then discards the
filled flag-holes -- a notehead is wider than it is tall, a flag hole is not.
Fill is measured afterwards, from the original ink, to report which of the
heads that were found are hollow.

It also replaces read_dyads.py, which split touching dyads and nothing else.

Dots are looked for only to the RIGHT of a head, only within a third of a space
of its own vertical centre, and only across a stretch that is LIGHT between the
head and the dot.  Those three conditions separate an augmentation dot from a
staccato dot (above or below), from the next notehead (a dot is under half a
space wide) and from the end of a ledger line (continuous with the head, so the
gap is dark) -- the ledger line was what put a phantom dot on every C4 and B3.

usage: read_heads.py --page 21 --sys 1 [--staves 3] [--staff 0] [--x 0.09,0.95]
                [--clef treble] [--key 4] [--dpi 2000] [--chunks N] [--debug]
"""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import read_staff as RS                                        # noqa: E402
from staff_comb import systems, SRC                            # noqa: E402

DEBUG_DOT = bool(os.environ.get('DEBUG_DOT'))


# Augmentation-dot distance window, in staff spaces from the notehead centre.
# See the gate in scan() for how these were measured.  What this buys, measured
# against the delivered tables for songs 12-14 as answer key: PRECISION is now
# clean -- 0 false dots over eight systems, down from 15 -- but RECALL is only
# partial, about half of song 13's printed dots.  So a dot this reports can be
# trusted; a dot it does NOT report proves nothing, and a bar that comes up
# short still has to be closed by arithmetic or by one look at the page.
DOT_LO, DOT_HI = 1.42, 1.85


def label_runs(mask):
    """Connected-component labels per run.  RS.components gives boxes only."""
    H, W = mask.shape
    runs, byrow = [], {}
    for r in range(H):
        row = mask[r]
        if not row.any():
            continue
        x = 0
        while x < W:
            if row[x]:
                x0 = x
                while x < W and row[x]:
                    x += 1
                byrow.setdefault(r, []).append(len(runs))
                runs.append((r, x0, x - 1))
            else:
                x += 1
    parent = list(range(len(runs)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for r in sorted(byrow):
        for i in byrow[r]:
            for j in byrow.get(r - 1, []):
                if runs[i][1] <= runs[j][2] and runs[j][1] <= runs[i][2]:
                    a, b = find(i), find(j)
                    if a != b:
                        parent[b] = a
    return [find(i) for i in range(len(runs))], runs


def fill_holes(mask):
    """Turn light regions fully enclosed by ink into ink."""
    H, W = mask.shape
    labels, runs = label_runs(~mask)
    touching = set()
    for lab, (r, x0, x1) in zip(labels, runs):
        if r == 0 or r == H - 1 or x0 == 0 or x1 == W - 1:
            touching.add(lab)
    out = mask.copy()
    for lab, (r, x0, x1) in zip(labels, runs):
        if lab not in touching:
            out[r, x0:x1 + 1] = True
    return out


def runlen(a):
    """Length of the maximal True run through every pixel, along axis 1."""
    H, W = a.shape
    pad = np.zeros((H, 1), bool)
    d = np.diff(np.hstack([pad, a, pad]).astype(np.int8), axis=1)
    out = np.zeros((H, W), np.int32)
    for r in range(H):
        st = np.nonzero(d[r] == 1)[0]
        en = np.nonzero(d[r] == -1)[0]
        for x0, x1 in zip(st, en):
            out[r, x0:x1] = x1 - x0
    return out


def strip_stems(mask, space):
    """Erase stems, barlines and the straight part of flags.

    Ink that is thin across and long down is never a notehead.  Removing it
    before the erosion pass fixes three separate failures at once: an
    eighth-note flag stops merging with its own head into a tall core that then
    splits into two or three phantom pitches; a barline stops being a
    candidate; and the clear-gap test that distinguishes an augmentation dot
    from a ledger line stops being blocked by the head's own up-stem, which
    leaves the head exactly where the gap is measured.
    """
    thin = runlen(mask) <= max(2, int(round(space * 0.34)))
    tall = runlen(mask.T).T >= max(3, int(round(space * 1.30)))
    return mask & ~(thin & tall)


def split_core(ymin, ymax, xmin, xmax, core, space):
    """Centres of the heads inside one eroded core blob, plus its height.

    Two filled heads a third apart touch, so they arrive as one component whose
    row profile still shows a hump per head -- that is the first test.  Two
    HOLLOW heads a third apart have no such waist once their rings are filled,
    and gave a single smooth blob whose centroid was the pitch of neither
    (song 11 bar 5 read F4 for a printed G4+E4).  So when the profile shows no
    humps the height decides: stacked heads only ever merge when they are a
    third apart -- a second is printed side by side, a fourth or wider leaves a
    light gap and separates on its own -- so a blob taller than one head is a
    column of heads one space apart, placed from its top and bottom edges.
    """
    h = (ymax - ymin + 1) / space
    sub = core[ymin:ymax + 1, xmin:xmax + 1]
    prof = sub.sum(axis=1).astype(float)
    humps, cur = [], []
    if len(prof) >= 3:
        lo = 0.55 * prof.max()
        for i, v in enumerate(prof):
            if v >= lo:
                cur.append(i)
            elif cur:
                humps.append(cur); cur = []
        if cur:
            humps.append(cur)
        humps = [g for g in humps if len(g) >= max(2, 0.22 * space)]
    if len(humps) >= 2:
        return [ymin + (g[0] + g[-1]) / 2 for g in humps], h
    if h <= 1.30:
        return [(ymin + ymax) / 2], h
    n = int(round(h - 0.80)) + 1
    inset = 0.42 * space
    top, bot = ymin + inset, ymax - inset
    if n <= 2:
        return [top, bot], h
    dy = (bot - top) / (n - 1)
    return [top + i * dy for i in range(n)], h


def scan(page, sysno, staves, staff, x0f, x1f, clef, key, dpi, pad=0.030,
         lo_step=-5, hi_step=9, after=None):
    st, H, _thr = systems(page, per=staves)
    lines = st[(sysno - 1) * staves + staff]
    top = max(0.0, lines[0] / H - pad)
    bot = min(1.0, lines[-1] / H + pad)
    a = RS.load(SRC, page, [x0f, top, x1f, bot], dpi)
    dark = a < 130
    fits, err = RS.staff_lines(dark)
    if err:
        return None, err, None
    Wpx = dark.shape[1]
    y_at = lambda f, x: f[0] * x + f[1]
    space = (y_at(fits[-1], Wpx // 2) - y_at(fits[0], Wpx // 2)) / 4
    clean = strip_stems(RS.strip_lines(dark, fits, space), space)
    solid = fill_holes(clean)
    vrun = runlen(dark.T).T      # for dots, which strip_lines destroys

    k = max(1, int(round(space * 0.27)))
    core = RS.erode(solid, k, 1) & RS.erode(solid, k, 0)
    filled_core = RS.erode(clean, k, 1) & RS.erode(clean, k, 0)

    cand = []
    for ymin, ymax, xmin, xmax, _area in RS.components(core):
        w = (xmax - xmin + 1) / space
        if not (0.40 <= w <= 1.45):
            continue                                  # beams are wide and flat
        cys, h = split_core(ymin, ymax, xmin, xmax, core, space)
        if h / len(cys) > 1.30:
            continue                                  # a stem that survived
        cx = (xmin + xmax) / 2
        for cy in cys:
            cand.append((cx, cy, xmin, xmax, len(cys)))

    # x of every head that is visible in the ORIGINAL ink, used to veto flag
    # holes: a flag encloses white directly above or below the stem, so it sits
    # at almost the same x as a head that is already accounted for.
    solidxs = [((xn + xx) / 2, (yn + yx) / 2)
               for yn, yx, xn, xx, _a in RS.components(filled_core)
               if 0.40 <= (xx - xn + 1) / space <= 1.45]

    ry, rx = max(1, int(0.15 * space)), max(1, int(0.26 * space))
    heads, ambig, oor = [], [], []
    for cx, cy, xmin, xmax, nstack in sorted(cand):
        step = (y_at(fits[-1], cx) - cy) / (space / 2)
        box = clean[max(0, int(cy) - ry):int(cy) + ry + 1,
                    max(0, int(cx) - rx):int(cx) + rx + 1]
        fill = float(box.mean()) if box.size else 1.0
        hollow = fill < 0.45
        if 0.50 < fill < 0.88:
            ambig.append(round(step, 2))
            continue      # neither solid nor hollow: a flag or beam remnant
        if hollow and any(abs(sx - cx) < 1.45 * space
                          and abs(sy - cy) > 1.4 * space for sx, sy in solidxs):
            continue                                  # an eighth-note flag
        # dot: a local THICKENING of the ink to the right of the head, at the
        # head's own height.  It cannot be looked for in `clean`, because an
        # augmentation dot printed ON a staff line is removed with the line --
        # which is exactly why song 13 bar 9's dot could not be seen at any
        # resolution.  Measured on the raw ink instead: a bare staff line is
        # about a tenth of a space thick, a dot a quarter, a notehead more than
        # half, so the dot is the only thing in that band with a vertical run
        # between the two.  Reading it off the raw ink also means a ledger line
        # (thin) and a stem (tall) are both excluded for free.
        # An augmentation dot on a note that sits ON a staff line is engraved
        # in the SPACE ABOVE it, not beside it -- so probing the head's own row
        # finds only the staff line, which is why every dot in song 13 came
        # back either missing or as a phantom.  Even steps are lines, odd steps
        # are spaces.
        dot = None
        onlin = int(round(step)) % 2 == 0
        row = int(round(cy - (0.50 * space if onlin else 0.0)))
        row = min(max(row, 0), vrun.shape[0] - 1)
        d0 = int(cx + 1.05 * space)
        d1 = min(vrun.shape[1], int(cx + 2.60 * space))
        if d1 - d0 > 5:
            seg = vrun[row, d0:d1].astype(float)
            base = float(np.median(seg))
            ok = (seg >= base + max(3.0, 0.10 * space)) & (seg <= 0.85 * space)
            best, bstart, run = 0, None, 0
            for i, v in enumerate(ok):
                if v:
                    run += 1
                    if run > best:
                        best, bstart = run, i - run + 1
                else:
                    run = 0
            if 0.12 * space <= best <= 0.60 * space:
                d = (d0 + bstart + best / 2 - cx) / space
                # DISTANCE gate, calibrated on song 14's four systems.  The
                # thickness test alone still fires on other ink in the band, and
                # the survivors separate by distance rather than by shape: the
                # three real dots there measured 1.54, 1.55 and 1.63 space from
                # the head centre, while every false positive was either
                # 1.13-1.35 (the neighbouring note's stem or beam, which the
                # engraver sets closer than a dot) or 2.1-2.5 (the next notehead
                # itself, or the eighth rest that follows a shortened note --
                # bar 6's 2.51 was that rest).  An engraver's dot sits a fixed
                # distance right of the head, so this is a property of the plate,
                # not of the bar; DOT_LO/DOT_HI are module-level so a differently
                # engraved book can be re-calibrated without touching the scan.
                if DOT_LO <= d <= DOT_HI:
                    dot = d
        if after is not None and x0f + cx / Wpx * (x1f - x0f) < after:
            continue      # clef bowl and key-signature accidentals read as heads
        if not (lo_step - 0.6 <= step <= hi_step + 0.6):
            oor.append(round(step, 2))
            continue          # above or below anything a voice part prints
        heads.append(dict(
            xfrac=x0f + cx / Wpx * (x1f - x0f),
            step=step, name=RS.name_of(int(round(step)), clef, key),
            frac=abs(step - round(step)), fill=fill, hollow=hollow,
            dot=dot, stack=nstack,
            w=(xmax - xmin + 1) / space, h=0.0))
    return heads, None, dict(ambig=ambig, oor=oor, space=space,
                             skew=abs(y_at(fits[-1], 0) - y_at(fits[-1], Wpx - 1)))


def scan_chunked(page, sysno, staves, staff, lo, hi, clef, key, dpi,
                 chunks=None, lo_step=-5, hi_step=9, after=None, target=0.12):
    """Scan a window in narrow slices and merge.

    A full system is about ten times wider than it is tall and the pages BOW,
    which read_staff cannot model -- it fits each staff line as a straight
    function of x.  Over a whole system that cost real pitches (page 12 bar 6
    read B3 full-width and C#4 in a narrow window), and here it lost a third of
    a duet's noteheads outright.  Slices about an eighth of the page wide keep
    the straight-line fit honest.
    """
    if chunks is None:
        chunks = max(1, int(round((hi - lo) / target)))
    w = (hi - lo) / chunks
    seen, notes = [], dict(ambig=[], oor=[], space=0.0, skew=0.0)
    for i in range(chunks):
        c0 = lo + i * w - (0.005 if i else 0)
        c1 = lo + (i + 1) * w + (0.005 if i < chunks - 1 else 0)
        heads, err, info = scan(page, sysno, staves, staff, c0, c1, clef, key,
                                dpi, lo_step=lo_step, hi_step=hi_step,
                                after=after)
        if err:
            continue
        notes['ambig'] += info['ambig']
        notes['oor'] += info['oor']
        notes['space'] = max(notes['space'], info['space'])
        notes['skew'] = max(notes['skew'], info['skew'])
        for hd in heads:
            dup = next((s for s in seen
                        if abs(hd['xfrac'] - s['xfrac']) < 0.0030
                        and abs(hd['step'] - s['step']) < 0.5), None)
            if dup is None:
                seen.append(hd)
            elif hd['frac'] < dup['frac']:
                dup.update(hd)          # keep the cleaner of two readings
    seen.sort(key=lambda h: (h['xfrac'], -h['step']))
    return seen, None, notes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--page', type=int, required=True)
    ap.add_argument('--sys', type=int, required=True)
    ap.add_argument('--staves', type=int, default=3)
    ap.add_argument('--staff', type=int, default=0)
    ap.add_argument('--x', default='0.09,0.95')
    ap.add_argument('--clef', default='treble')
    ap.add_argument('--key', type=int, default=0)
    ap.add_argument('--dpi', type=int, default=2000)
    ap.add_argument('--chunks', type=int, default=0,
                    help='0 = auto, about one per eighth of the page')
    ap.add_argument('--after', type=float, default=None,
                    help='ignore heads left of this x; the treble clef bowl and '
                         'each key-signature accidental read as noteheads')
    ap.add_argument('--range', default='-5,9',
                    help='plausible step range; a flag hole above the staff '
                         'reads as a notehead at step 11')
    ap.add_argument('--debug', action='store_true')
    a = ap.parse_args()

    lo, hi = [float(v) for v in a.x.split(',')]
    rlo, rhi = [float(v) for v in a.range.split(',')]
    seen, _err, info = scan_chunked(a.page, a.sys, a.staves, a.staff, lo, hi,
                                    a.clef, a.key, a.dpi,
                                    chunks=a.chunks or None,
                                    lo_step=rlo, hi_step=rhi, after=a.after)
    if a.debug:
        print(f'space={info["space"]:.0f}px skew={info["skew"]:.0f}px')
    if info['oor']:
        print(f'  ({len(info["oor"])} out-of-range dropped: {info["oor"]})',
              file=sys.stderr)
    if info['ambig']:
        print(f'  ({len(info["ambig"])} ambiguous dropped: {info["ambig"]})',
              file=sys.stderr)
    seen.sort(key=lambda h: (h['xfrac'], -h['step']))
    for hd in seen:
        tags = []
        if hd['hollow']:
            tags.append('HOLLOW')
        if hd['dot'] is not None:
            tags.append(f'DOT@{hd["dot"]:.2f}sp')
        if hd['stack'] > 1:
            tags.append(f'stack{hd["stack"]}')
        if hd['frac'] > 0.28:
            tags.append('*** BETWEEN PITCHES')
        geo = f' w={hd["w"]:.2f} h={hd["h"]:.2f}' if a.debug else ''
        print(f'{hd["name"]:>5} @{hd["xfrac"]:.4f}  step={hd["step"]:6.2f} '
              f'fill={hd["fill"]:.2f}{geo}  {" ".join(tags)}')
    print(f'({len(seen)} heads)')


if __name__ == '__main__':
    main()
