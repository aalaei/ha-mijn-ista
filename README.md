# ista Nederland — mijn.ista.nl

[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

Home Assistant integration for [mijn.ista.nl](https://mijn.ista.nl) — the Dutch ista energy monitoring portal.

## What it does

Exposes your heating, electricity, and cold water consumption as Home Assistant sensors, with:

- **Annual totals** — current year, previous year, year-over-year change %
- **Monthly breakdown** — per service, with building averages and prior months in attributes
- **Per physical meter** — individual readings for each device on your property
- **Building averages** — compare your usage against your building's average
- **Average temperature** — monthly outdoor temperature used for heating context

## Installation via HACS

1. In HACS → Integrations → ⋮ → Custom repositories
2. Add `https://github.com/aalaei/mijn-ista` with category **Integration**
3. Install **ista Nederland (mijn.ista.nl)**
4. Restart Home Assistant
5. Add integration: Settings → Devices & Services → Add Integration → search **ista Nederland**

## Configuration

| Field | Description |
|---|---|
| Email | Your mijn.ista.nl login email |
| Password | Your mijn.ista.nl password |
| Update interval | How often to poll the API (1–24 hours, default 24) |

## Notes

- Data on mijn.ista.nl updates every 3 days or monthly depending on your meter type
- No costs (EUR) sensors — the NL portal API does not expose billing amounts
- This integration is separate from the German [ecotrend-ista](https://github.com/Ludy87/ecotrend-ista) integration
