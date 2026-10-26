# Aurora — a solar weather station for the balcony

Aurora is a small outdoor weather station: one MCU board, three sensors, a
1.5 W solar panel and a single 18650 cell. It samples every five minutes and
pushes readings over Wi-Fi to a Raspberry Pi at home, which keeps a year of
history and serves the dashboard as a local web page.

## Goals

- **Six months on one charge.** A dark Nordic winter is the design case, not
  the sunny week in June.
- **No cloud.** Readings never leave the flat; the Pi is the only server.
- **Open hardware.** KiCad files, firmware and enclosure models in one repo.
- **Serviceable outdoors.** The sensor head opens with a single screw, so a
  corroded connector is a ten-minute fix instead of a rebuild.

## Non-goals

- **Forecasting.** Aurora records what happened. Prediction needs a model far
  bigger than the board and is somebody else's product.
- **Rain measurement.** A tipping bucket doubled the part count, the cost and
  the calibration work. Rain is a stretch goal for revision C at the earliest.
- **A mobile app.** The dashboard is a responsive page; a native app would be
  a second codebase to keep alive for no extra information.

## Architecture

Three layers, each replaceable on its own:

1. **Sensor head** — `SHT45` for temperature and humidity, `BMP390` for
   pressure, `VEML7700` for illuminance, all sharing one I²C bus. The choice
   and the rejected alternatives are written down in [decisions](decisions.md).
2. **Node** — an ESP32-C6 with a PCB antenna, a MOSFET-gated sensor rail and
   the solar charger. Deep sleep between samples; see the
   [power budget](battery-budget.md) for where the milliamps go.
3. **Base station** — a Raspberry Pi Zero 2 W running mosquitto and a small
   FastAPI service. It subscribes to `aurora/+/reading`, writes Parquet, and
   rebuilds the dashboard from yesterday's file.

## Hardware revision history

| Rev | Date    | What changed                                              |
|-----|---------|-----------------------------------------------------------|
| A   | 2026-05 | Breadboard proof of concept, BME280, USB power            |
| B   | 2026-08 | Custom PCB, SHT45, solar charger, 3D-printed enclosure    |
| C   | 2026-11 | Planned: external antenna option, sealed cable gland      |

## Current status

Revision B has been on the balcony since 2026-09-02. It survived two storms
and one wasp nest. The only open hardware issue is the antenna: the PCB
antenna is fine when the balcony door is open and drops to −78 dBm when it is
closed, which is exactly the winter case. Notes and the planned fix live in
[antenna notes](../../../notes/antenna-notes.md).

## Where to look next

- [Decisions](decisions.md) — why each part was chosen, and what lost.
- [Power budget](battery-budget.md) — the arithmetic behind "six months".
- [Retro, 2026-09-18](meetings/2026-09-18-retro.md) — what broke and who owns it.
