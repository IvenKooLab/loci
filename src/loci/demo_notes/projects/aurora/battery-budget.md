---
tags: [aurora, power]
---

# Aurora — power budget

Target: **six months on one charge**, with the station sampling every five
minutes (288 samples a day) through a Nordic winter.

## Where the milliamps go

| Consumer            | Current      | Time per sample | mAh / day |
|---------------------|--------------|-----------------|-----------|
| MCU awake           | 80 mA        | 1.2 s           | 7.68      |
| Wi-Fi burst         | 120 mA       | 0.15 s          | 1.44      |
| Sensor rail         | 0.9 mA       | 1.5 s           | 0.11      |
| Deep sleep (RTC on) | 12 µA        | 86,400 s        | 0.29      |
| **Total**           |              |                 | **9.52**  |

The MCU wake window dominates. Two thirds of it is the SHT45 conversion plus
the pressure oversample; cutting the pressure oversample from ×8 to ×4 saves
0.9 mAh a day, which is worth more than any sleep-current tuning at this point.

## Runtime arithmetic

- Cell: 18650, 2,600 mAh nominal.
- Usable down to the 3.0 V cutoff: ~2,100 mAh.
- Cold derating for −10 °C: ×0.85 → **1,785 mAh**.
- 1,785 / 9.52 ≈ **187 days ≈ 6.2 months**.

That is the six-month target with nothing to spare, which is the point: the
budget is supposed to be tight enough that a regression shows up as a warning
in the dashboard instead of a dead station in February.

## Solar

- Panel: 1.2 W at 6 V, fixed at 62° facing south-southwest.
- December, measured on the balcony: 0.12 h of equivalent full sun a day →
  ~39 mAh/day at the cell terminal, ~12 mAh/day after the charger's own draw
  and the panel's dirt.
- Draw is 9.52 mAh/day, so a clear December day roughly covers itself. The cell
  is insurance for the two-week overcast stretch, not the primary source.

## What would blow the budget

1. **Wi-Fi reconnect storms.** A dropped association retries every 30 s for up
   to ten minutes; one afternoon of that ate 60 mAh in the September soak.
   Fixed by capping retries at three and sleeping through the rest.
2. **A stuck sensor rail.** If the MOSFET gate floats, the rail stays on at
   1.4 mA and the day costs 34 mAh. The gate now has a 100 kΩ pull-down.
3. **Heating the enclosure.** A 0.5 W heater would triple the winter draw.
   Rejected; the sensors are specified to −40 °C and the cell is the only part
   that cares about cold.

## Open questions

- Is the 3.0 V cutoff leaving capacity on the table in summer, when the cell is
  warm? A warmer cell can safely go to 3.2 V, but the firmware would need a
  temperature-compensated cutoff, and that is revision C work.
- Should the sample interval stretch to ten minutes in December? It saves
  4.8 mAh/day and costs half the resolution of the storm data, which is the
  interesting part. Leaning no.
