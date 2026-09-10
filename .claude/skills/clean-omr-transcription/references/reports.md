# What a report means, and what to do about it

Load when a script reports something. Nothing here gates a delivery on its own
except `INVENTED`, which is rule 4.

- **`OVERLONG`** — a bar the ordered repairs could not fit. See
  `rare-repairs.md`. Never resolve it by deleting a note.
- **`short`** — a bar under its meter outside the legal pickup/final positions.
  Usually a missed meter, not a missed note. Do not pad it (rule 2).
- **`rhythm suspect`** — advisory. A dropped dot is the one rhythm error that
  passes every structural check, since the bar still fills its meter. Two signals
  catch it:
  - *Residue*: a bar ending in a rest shorter than a beat is the gap the missing
    dot left.
  - *Outlier*: a bar that would match a rhythm the song uses elsewhere if one dot
    were restored. This is the only signal when a dotted-eighth-plus-sixteenth
    was read as two eighths, which fills the beat exactly and leaves no gap.

  Both only say where to look. `--rhythm-support N` sets how many other bars must
  carry the repaired pattern (default 3; lower flags ordinary bars of four
  eighths).
- **`rest in non-primary voice` / `print-object="no"`** — the file will
  reintroduce hidden rests on the next round trip. Re-run with one voice per
  staff; `multi-part.md` explains why voice numbering misleads here.
- **`WRITE DID NOT CONVERGE`** — music21's exporter inflated a part's measure
  count (observed 301 → 418) with no error. `safe_write` already retried from the
  in-memory score five times. Do not re-parse and rewrite the written file; that
  compounds it. Confirm a manual MuseScore fix with the user rather than shipping
  corruption.
- **`INVENTED n dotted` / `n tuplets`** — a repair added ornaments the source does
  not have. Do not ship it. `rare-repairs.md` names the three repairs that can
  widen the vocabulary.
- **`anacrusis-rejected-by-arithmetic`** — a bar looked like a padded pickup but
  pickup + final didn't complete a bar. Check the source before overriding with
  `--anacrusis always`. Overriding does NOT fix the final bar: it unpads the
  pickup and leaves the arithmetic unbalanced. If the source engraves an upbeat,
  the final bar has to be shortened to complete it (pickup 0.5 + final 1.5 = one
  2/4 bar) — which is what a musician corrected by hand on book 6 song 1.
