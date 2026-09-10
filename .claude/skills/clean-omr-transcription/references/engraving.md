# Engraving: read the page before choosing tools

Load before starting a new book, or when a staff finder returns nonsense.

## Is there a melody staff at all?

SMOM 1-5 and 8 print melody + piano grand staff (3 staves per system). **Book 6
prints the vocal line INSIDE the piano treble staff** (2 staves, verses set
between them). There the crop route does not exist, `melody_staves.py
--per-system 3` finds nothing usable, and Audiveris' voice numbering does not
track the melody — in book 6 song 1, voice 1 filled only 9 of 17 bars.

Use `split_shared_staff.py`: the melody is the top line, recovered as a skyline.
Two failures there are systematic and expected —

- dropped dots on the dotted-eighth+sixteenth figure;
- melody notes sharing a notehead with the right hand, where the OMR merges them
  and the melody inherits the ACCOMPANIMENT's duration.

`reconcile_repeats.py` fixes both wherever the bar repeats one that read cleanly.

## Cropping the melody staff out

On a 3-staff book this is worth trying: `melody_staves.py book.pdf --pages 15-17
-o mel.pdf`, one system per page. Leave `--dpi` alone — Audiveris refuses images
over 20M pixels.

The accompaniment is what scrambles part assignment. A grand staff below the
vocal line makes Audiveris hand measures to the wrong part, silently drop a page,
or die outright — `Denominator is zero` at every resolution, clean once the piano
was gone.

## Finding staves

**Use `staff_comb.py`, not a darkness threshold.** Thresholding the dark-row
fraction misses faint staves outright: three book 8 pages reported 5, 4 and 2
staves instead of 6, and no single threshold fixed all three without inventing
staves elsewhere (0.35 turned another page into 8). A staff is not "5 dark rows"
but five EQUALLY SPACED ones, which is what the comb scores; it measures the line
spacing from the page itself, so it needs no per-page tuning.

`find_title_bands.py` and `melody_staves.py` still have gap and minimum-height
constants tuned for **portrait** pages. Book 6's landscape scans (768x500pt)
render too small at the default `--scale`, so every staff fails the five-line
test. Raise `--scale` and check the reported staff count against a page you have
actually looked at.

If the book has a printed contents page, reading it is far cheaper than reading
title bands.
