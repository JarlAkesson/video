#!/usr/bin/python3
"""Bake the Logic layout into the MIDI: the song repeated at given bars, one file.

usage: arrange_midi.py <stem>.mid --starts 4,22,40 [--out <stem>_logic.mid]
                       [--end-bar 54 --tonic E [--minor]]

--end-bar/--tonic add the ENDING (user's SMOM 5 song 5): at --end-bar, ringing 3 bars,
melody root (C3..B3) v69, piano voicing root-24/root-12+3rd/root v58, and the dominant
root a 4th below the bottom note in the bar before (last beat in 3/4, last half-bar
otherwise), v58. Output track order then = Ending(piano), chords, melody, so Logic makes
track 9 = piano ending, 10 = chords, 11 = melody (copy it to the two "Melody" tracks).
Convention for --end-bar: final song measure + 4 (session players run 3 more bars).

--starts are the Logic bars where SONG BAR 1 goes (a pickup bar counts as song bar 1,
so with a pickup the first downbeat is start+1). Import the result at bar 1 with
"Import Tempo": every note lands at its final position, so no Move to Playhead and
no copy/paste in Logic. Track names/programs/channels are kept from the source
(MuseScore export: "Grand Piano" melody, "Melody" block chords).
"""
import argparse, os, struct, sys


def vlq_read(b, i):
    v = 0
    while True:
        c = b[i]; i += 1
        v = (v << 7) | (c & 0x7F)
        if c < 0x80:
            return v, i


def vlq(v):
    out = [v & 0x7F]
    v >>= 7
    while v:
        out.append((v & 0x7F) | 0x80); v >>= 7
    return bytes(reversed(out))


def read(path):
    return read_bytes(open(path, "rb").read())


def read_bytes(b):
    assert b[:4] == b"MThd"
    fmt, ntrk, div = struct.unpack(">HHH", b[8:14])
    i, tracks = 14, []
    for _ in range(ntrk):
        assert b[i:i + 4] == b"MTrk"
        ln = struct.unpack(">I", b[i + 4:i + 8])[0]
        j, end, t, run, ev = i + 8, i + 8 + ln, 0, None, []
        while j < end:
            d, j = vlq_read(b, j); t += d
            st = b[j]
            if st == 0xFF:
                typ = b[j + 1]; n, k = vlq_read(b, j + 2)
                ev.append((t, bytes([0xFF, typ]) + vlq(n) + b[k:k + n])); j = k + n
            elif st in (0xF0, 0xF7):
                n, k = vlq_read(b, j + 1)
                ev.append((t, bytes([st]) + vlq(n) + b[k:k + n])); j = k + n
            else:
                if st & 0x80:
                    run = st; j += 1
                n = 1 if (run & 0xF0) in (0xC0, 0xD0) else 2
                ev.append((t, bytes([run]) + b[j:j + n])); j += n
        tracks.append(ev); i = end
    return fmt, div, tracks


def is_setup(e):
    """Meta (except end-of-track) and program/controller events at tick 0: keep once."""
    st = e[0]
    return st == 0xFF or (st & 0xF0) in (0xB0, 0xC0)


def bar_ticks(tracks, div):
    for ev in tracks:
        for t, e in ev:
            if e[:2] == b"\xFF\x58":
                n, d = e[3], 2 ** e[4]
                return div * 4 * n // d, f"{n}/{d}"
    return div * 4, "4/4"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("--starts", required=True); ap.add_argument("--out")
    ap.add_argument("--end-bar", type=int); ap.add_argument("--tonic"); ap.add_argument("--minor", action="store_true")
    a = ap.parse_args()
    fmt, div, tracks = read(a.src)
    bt, sig = bar_ticks(tracks, div)
    starts = [int(x) for x in a.starts.split(",")]
    out_tracks = []
    for ev in tracks:
        setup = [(0, e) for t, e in ev if t == 0 and is_setup(e) and e[:2] != b"\xFF\x2F"]
        notes = [(t, e) for t, e in ev if not is_setup(e)]
        new = list(setup)
        for s in starts:
            off = (s - 1) * bt
            new += [(t + off, e) for t, e in notes]
        new.sort(key=lambda x: x[0])   # stable: keep the source's order within a tick
                                       # (unison voices emit on/off/on at one tick)
        last = new[-1][0] if new else 0
        body, prev = b"", 0
        for t, e in new:
            body += vlq(t - prev) + e; prev = t
        body += vlq(0) + b"\xFF\x2F\x00"
        out_tracks.append(body)
    if a.end_bar:
        # User's song-5 ending (checked in the saved session): in bar --end-bar, ringing 3 bars,
        #   melody  : tonic root (Logic C3..B3 octave), velocity 69
        #   piano   : root-24, root-12+third, root at velocity 58, plus the DOMINANT root a
        #             fourth below the bottom note, velocity 58, in the bar before:
        #             last beat in 3/4, last half-bar in 2/4, 4/4, 6/8.
        pc = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}[a.tonic[0].upper()]
        pc = (pc + a.tonic[1:].count("#") - a.tonic[1:].count("b")) % 12
        root = 60 + pc
        third = 3 if a.minor else 4
        t0, ring = (a.end_bar - 1) * bt, 3 * bt
        num = int(sig.split("/")[0]); den = int(sig.split("/")[1])
        pick = bt // num if (num, den) == (3, 4) else bt // 2
        voicing = [root - 24, root - 12 + third, root]
        dom = root - 24 - 5

        def note_evs(p, start, dur, vel):
            return [(start, bytes([0x90, p, vel])), (start + dur, bytes([0x80, p, 0]))]

        def splice(body, extra):          # insert events into an encoded track body
            _, _, [ev] = read_bytes(b"MThd" + struct.pack(">IHHH", 6, 1, 1, div) +
                                    b"MTrk" + struct.pack(">I", len(body)) + body)
            ev = [e for e in ev if e[1][:2] != b"\xFF\x2F"] + extra
            ev.sort(key=lambda x: (x[0], 0 if (x[1][0] & 0xF0) == 0x80 else 1))
            b2, prev = b"", 0
            for t, e in ev:
                b2 += vlq(t - prev) + e; prev = t
            return b2 + vlq(0) + b"\xFF\x2F\x00"

        melody = splice(out_tracks[0], note_evs(root, t0, ring, 69))
        piano = [(0, b"\xFF\x03\x06Ending"), (0, bytes([0xC0, 0]))]
        piano += note_evs(dom, t0 - pick, pick, 58)
        for p in voicing:
            piano += note_evs(p, t0, ring, 58)
        ending = splice(vlq(0) + b"\xFF\x2F\x00", piano)
        # track order -> Logic tracks 9, 10, 11: Ending (piano), block chords, melody
        out_tracks = [ending, out_tracks[1], melody]
        print(f"ending bar {a.end_bar}: melody {root} v69; piano {voicing} v58, 3 bars; "
              f"dominant {dom} at {(t0 - pick) / bt + 1:.3f} for {pick} ticks")
    out = a.out or os.path.splitext(a.src)[0] + "_logic.mid"
    with open(out, "wb") as f:
        f.write(b"MThd" + struct.pack(">IHHH", 6, 1, len(out_tracks), div))
        for body in out_tracks:
            f.write(b"MTrk" + struct.pack(">I", len(body)) + body)
    print(f"{sig}, {bt} ticks/bar, song bar 1 at Logic bars {starts} -> {out}")


if __name__ == "__main__":
    main()
