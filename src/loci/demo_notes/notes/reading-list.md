---
tags: [reading]
---

# Reading list

Books and papers that changed how I build things, with the one idea I actually
kept from each. Pruned twice a year; anything not re-read in three years goes.

## Electronics

- **The Art of Electronics** (Horowitz & Hill) — chapter 9 on voltage
  references is the reason the pressure sensor stopped drifting with supply.
  Not a book to read end to end; a book to keep next to the bench.
- **High-Speed Digital Design** (Johnson & Graham) — half of it is about
  problems a 5-minute-sample board will never have, but the grounding chapter
  is why the sensor rail and the radio share exactly one ground point.

## Software

- **A Philosophy of Software Design** (Ousterhout) — "deep modules" is the
  argument for the single `read_sensors()` call that hides three I²C devices
  behind one struct. Also the argument against the plugin system I wanted.
- **Designing Data-Intensive Applications** (Kleppmann) — the Parquet-per-day
  layout came straight from the chapter on batch processing; it turned a year
  of history into a directory listing.

## Papers and articles

- *Deep Sleep on ESP32-C6: measured numbers* (a forum thread, not a paper) —
  the 12 µA figure in the power budget is from here, not from the datasheet.
  The datasheet says 7 µA, which requires turning off more than the examples
  do.
- *Understanding I²C bus capacitance* — the reason the sensor head is 40 cm of
  cable and not 1 m. At 400 kHz the bus was marginal at 80 cm in the freezer.

## To read

- Something practical on LiFePO4, if the 18650 gets replaced in rev D.
- A proper text on enclosure sealing (IP54 without a gasket supplier).
