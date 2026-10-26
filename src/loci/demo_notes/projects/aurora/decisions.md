---
tags: [aurora, hardware, adr]
---

# Aurora — decision records

Short records, one per decision. Each keeps the options that lost, because the
reasons usually matter more than the winner.

## ADR-001: SHT45 over BME280 for temperature and humidity

**Context.** Revision A used a BME280 because it was already in the parts bin
and does temperature, humidity and pressure in one package.

**Options.**

| Part    | RH accuracy | Temp accuracy | Condensation | Price  |
|---------|-------------|---------------|--------------|--------|
| BME280  | ±3 %        | ±0.5 °C       | sensitive    | €2.10  |
| SHT45   | ±1.0 %      | ±0.1 °C       | robust       | €4.60  |
| DHT22   | ±2 %        | ±0.5 °C       | poor         | €1.80  |

**Decision.** SHT45. The balcony sits between 80 % and 100 % relative humidity
for most of the winter, and the BME280 drifted upward by roughly 6 % RH after
two months of that. A sensor whose error grows exactly where it is installed
is not worth the €2.50 saved. The pressure channel moved to a BMP390, which is
cheaper than the BME280 and does one job.

**Consequences.** Two packages instead of one, so the head needs a slightly
larger opening. The offset calibration sheet is now per-unit and lives next to
the firmware config.

## ADR-002: ESP32-C6 over nRF52840

**Context.** The node needs Wi-Fi, deep sleep under 20 µA, and a toolchain a
weekend can absorb.

**Options.**

- **ESP32-C6** — Wi-Fi 6 and BLE, ~12 µA in deep sleep with the RTC running,
  mature ESP-IDF, €3.40.
- **nRF52840** — better sleep numbers (~2 µA) but no Wi-Fi; would need a
  separate radio or a BLE gateway on the Pi.

**Decision.** ESP32-C6. The nRF52840 wins on sleep current, but the difference
is 10 µA against a 1.2 mA average — it changes the battery estimate by less
than a day. Adding a BLE-to-MQTT gateway would cost more than the whole node.

**Consequences.** The firmware is ESP-IDF, so the build is heavier than a
bare-metal loop. A local `idf.py` install is 1.8 GB; this is the real price of
the decision, and it is paid once.

## ADR-003: 18650 cell with a BQ25570 charger, no boost converter

**Context.** The panel is 1.5 W at 6 V, the cell sits at 3.7 V nominal, the
board runs at 3.3 V.

**Decision.** Charge the cell directly through a BQ25570 and run the board
from the cell via a low-dropout regulator. A boost converter would waste 8–12 %
of a very small harvest to save nothing.

**Consequences.** The board stops at 3.0 V, which is where the cell's knee
starts and where the fuel gauge is still honest. Anything below that is
recovered by hand, on the bench, not outdoors.

## ADR-004: PETG enclosure, printed in two halves

**Context.** ASA is UV-stable, PETG is easier to print and available locally.

**Decision.** PETG, painted with a matte UV clear coat, reprinted every two
years. A €3 print that lasts two summers beats a €9 print that needs a heated
chamber to make.

**Consequences.** The clear coat is a consumable, and the vent slots have to
be re-masked every time. Annoying, but visible in the maintenance calendar.
