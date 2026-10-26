---
tags: [hardware, rf]
---

# Antenna notes — PCB vs external

Running notes for the rev C antenna question. Related: the
[[battery-budget]] does not have room for a powered LNA, and
[[decisions]] has not recorded a choice yet because there is not one.

## The measurement

RSSI to the access point, sampled hourly for a week (2026-09-05 → 09-12):

| Condition              | Mean RSSI | Retries / 100 sends |
|------------------------|-----------|---------------------|
| Balcony door open      | −61 dBm   | 2                   |
| Balcony door closed    | −78 dBm   | 19                  |
| Door closed, winter coat hanging between | −84 dBm | 41 |

The door is a steel-framed balcony door. The PCB antenna is a meandered
inverted-F tuned for free space; standing next to a metal plane detunes it and
kills the pattern on the far side.

## Options

1. **External 2.4 GHz whip on a U.FL pigtail.** Best gain (+6 dBi claimed,
   probably +3 real). Costs €4, a hole in the enclosure, and a cable gland.
   Also the most waterproofing risk, because it is the only hole below the
   gasket.
2. **Keep the PCB antenna, move the node.** Put the node on the outside of the
   door frame, run power from inside. Zero new parts, but the cable run is now
   outdoors and the panel would shade the sensor head.
3. **Switched antenna diversity.** Two antennas, pick the better RSSI per
   sample. This is a €12 radio and a lot of firmware for a problem a €4 whip
   solves.

## What I think

Option 1, with the gland placed on the bottom face so any leak runs away from
the board. The moisture risk is real but it is the same class of risk as the
sensor opening, which has held for two months.

## To verify before committing

- Does the pigtail fit next to the 18650 holder? The rev B board has 3 mm of
  clearance and the U.FL connector is 2.5 mm tall with the cable bending.
- Measure current draw with the whip at −61 dBm: fewer retries should show up
  as ~0.4 mAh/day saved, which is real but not decisive.
- Order two pigtails; the first will be destroyed by the learning process.

## Links

- [[decisions]] — ADR-002 has the ESP32-C6 choice, which fixed the antenna
  options at the module footprint.
- [[battery-budget]] — the retry-storm line item is the cost of a bad antenna.
