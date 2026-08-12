# Multi-part scores: grand staff and combined books

Load when the deliverable includes accompaniment or a combined whole-book score.
A melody-only run needs none of this.

## Grand staff

- Use `stream.PartStaff` per hand joined by
  `layout.StaffGroup([rh, lh], symbol='brace')` → one `<score-part>` with
  `<staves>2</staves>`, not two separate instruments.
- Strip leftover `Instrument` objects and set `instrument.Piano()` explicitly,
  or MuseScore shows the wrong instrument despite a correct `partName`. Same for
  the melody: an inherited "Voice" instrument overrides the part name on every
  system after the first.
- **Voice numbers are shared across a grand staff's two staves.** The left
  hand's own first voice is typically numbered 3 or 5, never 1. "Voice 1" is not
  the test for SKILL.md §5 — compute the primary (lowest-numbered) voice per
  staff, or you strip the left hand of every rest it is entitled to keep.

## Cross-part measure-number gaps

Watch for parts with matching measure *counts* but mismatched *numbers*
(Melody `1..9` vs Piano `2..10`). Padding a rest measure at the **end** hides
the mismatch while shifting every measure's position — which compounds across
songs during combined-score assembly into gross corruption.

- Correct fix: take the part with the most measures as the reference number
  sequence, find which numbers each other part is missing, and insert padding
  at the correct **ordinal position**.
- Per-song counts matching is not proof — always verify the final combined
  score's per-part measure counts too.
