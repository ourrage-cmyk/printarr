# Handoff: image-based receipt templates for printarr

For the API thread. Six designs to implement first. They use round 4 (B4-xxx on the rating page) and the taste profile in docs/design/taste-profile.md. Entity IDs come from ha-entities.md in this folder. Items marked **rendered** were drawn and checked in the simulator. Items marked **derived** follow the same rules but were not rendered yet.

## Print facts (all designs)
- Paper: 80 mm, 512 dots wide at 180 dpi (about 72 mm of print). One dot is about 0.14 mm.
- Each ticket is one 1-bit bitmap, 512 dots wide and 250 to 700 rows tall.
- Send it with GS ( L function 112. Body `48, 112, 48, 1, 1, 49`, then width and height as 16-bit little-endian, then the rows packed MSB first, 1 = black. Follow with GS ( L `2, 0, 48, 50` (print buffer). printarr's `app/escpos.py` `_raster` already does this, and `Line.raster` takes `(width_bytes, height, data)`.
- End with one feed line, then a partial cut (`ESC d 1`, `GS V 1`). Do not use the usual 4-line feed, which leaves a blank strip on a raster ticket.
- Text is drawn with the 5x7 dot font in `design-lab/lib/raster.js`. Do not mix it with the printer's Font A on one ticket.

## Type on the 1-bit grid
| Role | Scale | Cap height | Used for |
|---|---|---|---|
| Hello title | 3 (4 for big greetings) | 21 dots, about 3 mm | "HELLO YANNIC" |
| Body and labels | 2 | 14 dots, about 2 mm | labels, rows, sentences |
| Values in rows | 2 | 14 dots | "0.0757 GBP" |
| Numerals (rarely) | 3 | 21 dots | only where one number matters |

Do not go below scale 2. Scale 1 is about 1 mm and does not print legibly.

## Cards and layout
- Outlined cards only: a 2-dot stroke around each card. No fill, no shadow.
- Corner radius from the Material 3 scale: 4, 8 or 12 dots (**rendered** in round 4).
- Inner padding 14 dots. Gap between cards 8 to 12 dots (**rendered**).
- Card edges 14 dots from the paper edge (**rendered**).
- Card height is set by its content (**rendered**). No fixed heights.
- Section heading inside the card, then rows.
- Rows: label on the left, dot leaders, value right-aligned at the card edge (**rendered**).
- Segmented bar: 20 segments, 10 dots tall, 4-dot gap, empty segments as dots (**rendered**).
- Line graph: 56 dots tall, axes and dotted gridlines, no area fill (**rendered**).
- Alert pill: filled rounded box with the label in white (**rendered**).

## Entity map
Renders use sample values. Live values come from HA at print time.

| Field | Entity | Unit |
|---|---|---|
| Yannic body battery | `sensor.body_battery_most_recent` | % |
| Yannic body battery high / low | `sensor.body_battery_highest` / `sensor.body_battery_lowest` | % |
| Yannic sleep score | `sensor.sleep_score` | score |
| Yannic stress average | `sensor.avg_stress_level` | level |
| Yannic steps | `sensor.total_steps` | steps |
| Yannic resting heart rate | `sensor.resting_heart_rate` | bpm |
| Yannic phone battery | `sensor.yannic_pixel_battery_level` | % |
| the second person body battery | `sensor.body_battery_most_recent_2` | % |
| the second person sleep score | `sensor.sleep_score_2` | score |
| the second person stress average | `sensor.avg_stress_level_2` | level |
| the second person steps | `sensor.total_steps_2` | steps |
| the second person resting heart rate | `sensor.resting_heart_rate_2` | bpm |
| the second person HRV last night | `sensor.garmin_connect_hrv_last_night_average_2` | ms |
| Electricity now | `sensor.octopus_energy_electricity_<meter>_current_rate` | GBP/kWh |
| Electricity next half-hour | `sensor.octopus_energy_electricity_<meter>_next_rate` | GBP/kWh |
| Electricity cost per hour | `sensor.realtime_energy_cost` | GBP/h |
| Money saved total | `sensor.money_saved_total` | GBP |
| Money saved rate | `sensor.money_saved_rate` | GBP/h |
| Next day rates (cheapest window) | `event.octopus_energy_electricity_<meter>_next_day_rates` | computed |
| Indoor temperature | `sensor.home_temperature` | C |
| Indoor humidity | `sensor.home_humidity` | % |
| Outdoor temperature | `weather.forecast_home`, attribute `temperature` | C |
| Outdoor 24-hour history for the line graph | `weather.forecast_home` or the recorder history API for an outdoor sensor | C |
| Rain chance | `weather.get_forecasts` service (`type: hourly`), field `precipitation_probability` | % |
| Heating on | `input_boolean.heating` | on/off |
| Bridget peed / poop / food / runs | `counter.bridget_peed`, `counter.bridget_poop`, `counter.bridget_food`, `counter.bridget_runs` | count |
| Kida peed / poop / food / runs | `counter.kida_peed`, `counter.kida_poop`, `counter.kida_food`, `counter.kida_runs` | count |
| Server CPU | `sensor.truenas_cpu_usage` | % |
| Server pool usage | `sensor.truenas_pool_usage` | % |
| HDD max temperature | `sensor.hdd_max_temperature` | C |
| HA host RAM | `sensor.system_monitor_memory_usage` | % |
| Pending updates | `update.*` with state `on` | count |
| Backup next scheduled | `sensor.backup_next_scheduled_automatic_backup` | timestamp |

Not usable: `switch.heating` (unavailable), `sensor.plants_humidity` (unavailable), any `glances` TrueNAS entity (missing).

## Computed or optional fields
- **Cheapest window:** no entity gives it. Compute it from `event.octopus_energy_..._next_day_rates`. Confirm the event's attribute shape before using it.
- **Rain chance:** not in the state attributes. Use `weather.get_forecasts`. Until the API thread wires it up, leave it out.
- **Bin day, reminders, household calendar:** no entities exist. Design those as optional fields. Print the line only when a value exists.
- **Shopping list:** `todo.shopping_list` exists, but it has 0 items right now.
- **Dog counters:** they reset on a schedule or by hand. Check the reset automation before showing daily totals.
- **Outdoor 24-hour history:** `weather.forecast_home` has only the current temperature. Use the recorder history API for an outdoor sensor, or leave the graph out until that is wired.

## The six designs

### 1. Morning, Yannic (based on B4-014: Hello + Rows + Segbar, r4, scale 2) — rendered
- Card 1: "HELLO YANNIC" (scale 3), then a summary sentence (scale 2).
- Card 2: "TODAY". Rows: BODY BATTERY, STRESS AVG, STEPS.
- Card 3: segmented bars: BODY BATTERY, CPU, RAM. CPU is `sensor.truenas_cpu_usage`, RAM is `sensor.system_monitor_memory_usage` (HA host, not the NAS).
- Summary sentence: outdoor temperature, and rain chance when the forecast call is wired up.

### 2. Morning, the second person (derived from B4-014 with her fields) — derived
- Greeting "HELLO ALLYSON".
- Card 2 rows: SLEEP SCORE, STRESS AVG, STEPS, from the `_2` sensors.
- Card 3: segmented bar for her sleep score (out of 100), and a comparison card (Yannic vs the second person, as in B4-007) when wanted.

### 3. Evening, Yannic (based on B4-003: Hello + Energy + Segbar, r12, scale 2) — rendered
- Card 1: greeting and summary.
- Card 2: ENERGY. Rows NOW and NEXT (GBP/kWh, 4 decimals). Then a 24-hour line graph, once the outdoor history is wired (see above). Optionally the cheapest window line.
- Card 3: segmented bars for body battery, CPU and RAM.

### 4. Evening, dogs (based on B4-010: Hello + Compare + Dogs, r12, scale 3) — rendered
- Card 1: greeting.
- Card 2: Yannic vs the second person comparison (steps, stress).
- Card 3: DOGS TODAY, one row per dog: P (peed), O (poop), F (food), R (runs), from the counter entities above.

### 5. Alert (based on B4-012: Hello + Segbar + Alert, r8, scale 3) — rendered
- Card 1: greeting line only.
- Card 2: alert pill with a short message, for example PEAK 16:00. The peak time is computed from the next-day rates event. One sentence below.
- Card 3: segmented bar for the value that triggered the alert, for example the current rate as a fraction of its highest rate.
- Also useful: pending updates count (`update.*` on), or the backup line.

### 6. Shopping list or note (derived from B2-031, outlined radius 4, checkbox rows) — derived
- No greeting. One title line in the body scale, "SHOPPING".
- One outlined card with checkbox rows (box sprite, then the item in body scale), up to 8 items. The list comes from `todo.shopping_list`, which is empty now, so print a note line "LIST EMPTY" when there are no items.
- A second card for a note sentence, if needed.

## Limits
- Renders use sample numbers. Live values come from HA at print time, as printarr already does for `blocks`.
- If a value is missing at print time, print the row with "NO DATA" in its value position. Do not drop the row, so the layout stays fixed.
- Use ASCII only. The 5x7 font has no accents or degree sign, so write "C" for Celsius and "GBP".
- Entities that report "Entity not found" or "unavailable" must not be printed as values.
