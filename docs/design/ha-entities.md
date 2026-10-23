# Home Assistant entities for receipts

Entity IDs, units and notes from a read-only snapshot (2026-10-24). Live values are omitted. Personal and location data are removed.

## Yannic (Garmin and Pixel)

| Entity | Unit | Note |
|---|---|---|
| sensor.body_battery_most_recent | % | Latest reading. History: yes (measurement). |
| sensor.body_battery_highest | % | Daily high. History: yes. |
| sensor.body_battery_lowest | % | Daily low. History: yes. |
| sensor.sleep_score | score | Last night. History: yes. |
| sensor.yannic_pixel_sleep_duration | min | Last night. Pixel source. History: no state_class. |
| sensor.avg_stress_level | level | Daily average. History: yes. |
| sensor.total_steps | steps | Running total for the day. History: yes (total_increasing). |
| sensor.resting_heart_rate | bpm | Garmin. History: yes. |
| sensor.yannic_pixel_resting_heart_rate | bpm | Pixel source of the same value. |
| sensor.yannic_pixel_heart_rate_variability | ms | HRV source. History: no state_class. |
| sensor.yannic_pixel_vo2_max | mL/kg/min | Pixel source. |
| sensor.yannic_pixel_battery_level | % | Phone battery. |
| binary_sensor.yannic_pixel_is_charging | on/off | Unplug trigger. History: yes. |
| sensor.yannic_pixel_do_not_disturb_sensor | state | Presence context. |

Missing: there is no HRV entity with a `_2` suffix for Yannic. The `garmin_connect_hrv_*_2` entities belong to Allyson.

## Allyson (Garmin and Pixel)

| Entity | Unit | Note |
|---|---|---|
| sensor.body_battery_most_recent_2 | % | Latest reading. History: yes. |
| sensor.sleep_score_2 | score | Last night. History: yes. |
| sensor.total_sleep_duration_2 | min | Last night. History: yes. |
| sensor.avg_stress_level_2 | level | Daily average. History: yes. |
| sensor.total_steps_2 | steps | Running total. History: yes. |
| sensor.resting_heart_rate_2 | bpm | History: yes. |
| sensor.garmin_connect_hrv_last_night_average_2 | ms | HRV. History: yes. |
| sensor.garmin_connect_hrv_weekly_average_2 | ms | History: yes. |
| sensor.hrv_status | text | Qualitative. |
| sensor.allyson_pixel_battery_level | % | Phone battery. |
| binary_sensor.allyson_pixel_is_charging | on/off | Unplug trigger. |
| sensor.allyson_pixel_do_not_disturb_sensor | state | Presence context. |

## Octopus Agile (electricity)

| Entity | Unit | Note |
|---|---|---|
| sensor.octopus_energy_electricity_<meter>_current_rate | GBP/kWh | Live rate. History: yes. |
| sensor.octopus_energy_electricity_<meter>_next_rate | GBP/kWh | Next half-hour. History: yes. |
| sensor.octopus_energy_electricity_<meter>_previous_rate | GBP/kWh | History: yes. |
| sensor.octopus_energy_electricity_<meter>_current_standing_charge | GBP | Daily standing charge. |
| sensor.octopus_energy_electricity_<meter>_previous_accumulative_cost | GBP | Cumulative. |
| sensor.octopus_energy_electricity_<meter>_previous_accumulative_consumption | kWh | Cumulative. |
| sensor.electricity_rate_statistics_3_months | GBP/kWh | Reference only. |
| sensor.octopus_energy_monthly_rolling_average | GBP/kWh | Reference only. |
| sensor.realtime_energy_cost | £/Hour | Live house cost. |
| sensor.money_saved_total | GBP | Savings total. History: yes (total). |
| sensor.money_saved_rate | GBP/h | Savings rate. History: yes. |
| event.octopus_energy_electricity_<meter>_next_day_rates | event | Holds tomorrow's rate blocks. Use this for the cheapest window. |
| binary_sensor.octopus_energy_electricity_<meter>_off_peak | on/off | Off-peak flag. |
| calendar.octopus_energy_a_<account>_octoplus_saving_sessions | calendar | Saving sessions. |
| binary_sensor.octopus_energy_a_<account>_octoplus_saving_sessions | on/off | Unavailable right now. |

Cheapest window: no single HA entity gives it. Compute it from `event.octopus_energy_..._next_day_rates` (rate blocks in its attributes), or from the rate entities over time. Confirm the event's attribute shape before using it.

## House

| Entity | Unit | Note |
|---|---|---|
| sensor.home_temperature | °C | Indoor. History: yes. |
| sensor.home_humidity | % | Indoor. History: yes. |
| sensor.average_humidity_bathroom_2 | % | Bathroom reading. |
| input_boolean.heating | on/off | Heating master switch. |
| input_button.heat_now | button | Last press. |
| timer.heat_now_boost | timer | Boost timer. |
| binary_sensor.winter_heating_season | on/off | Season flag. |
| binary_sensor.radiator_office | on/off | Radiator status. |
| binary_sensor.radiator_kitchen | on/off | |
| binary_sensor.radiator_living_room | on/off | |
| binary_sensor.radiator_bedroom | on/off | |
| binary_sensor.radiator_bathroom_a | on/off | |
| binary_sensor.radiator_bathroom_2 | on/off | |
| sensor.trv_office_battery | % | TRV battery. Kitchen TRV is 55%. Listed on the Energy dashboard. |
| binary_sensor.trv_*_battery_plus_low | on/off | All TRVs currently off (not low). |
| switch.heating | switch | Unavailable. Do not use for receipts. |

Missing or unavailable: `switch.heating` is unavailable. `sensor.plants_humidity` is unavailable.

## Dogs (counters)

| Entity | Unit | Note |
|---|---|---|
| counter.bridget_peed | count | Daily counter. History: counter, yes. |
| counter.bridget_poop | count | |
| counter.bridget_food | count | |
| counter.bridget_runs | count | |
| counter.kida_peed | count | |
| counter.kida_poop | count | |
| counter.kida_food | count | |
| counter.kida_runs | count | |

Note: these counters reset on a schedule or by hand. The reset timing is not confirmed here; check the automation that resets them before relying on daily totals.

## Weather

| Entity | Unit | Note |
|---|---|---|
| weather.forecast_home | state | Met.no. Temperature (5.1 °C), humidity (91%), dew point, wind, pressure are attributes. |
| weather.forecast_home (attribute `temperature`) | °C | Outdoor reading for the house. |

Rain chance: the current-state attributes do not include a precipitation probability. Get it with the `weather.get_forecasts` service (daily or hourly), not from the state.

## Calendars

| Entity | Friendly name | State | Note |
|---|---|---|---|
| calendar.serverroom_sonarr | Sonarr | off | Upcoming episodes. |
| calendar.radarr | Radarr | off | Upcoming films. |
| calendar.octopus_energy_a_<account>_octoplus_power_down | Octoplus Power Down | off | Octopus event calendar. |
| calendar.octopus_energy_a_<account>_octoplus_saving_sessions | Octoplus Saving Sessions | off | Octopus event calendar. |

No household calendar (family, work, or a Google/iCloud calendar) is present, so receipts can't pull events from HA yet.

## Bins and reminders

No bin day, waste collection, or reminder entity was found. Search terms used: bin, waste, rubbish, recycl, reminder, todo. A shopping list exists (`todo.shopping_list`, 0 items). If bin days matter, the schedule needs to be added to HA first.

## Server health (NAS and HA)

| Entity | Unit | Note |
|---|---|---|
| sensor.truenas_cpu_usage | % | History: yes. |
| sensor.truenas_cpu_load | (none) | |
| sensor.truenas_cputin_temperature | °C | |
| sensor.truenas_pool_usage | % | Pool usage. |
| sensor.truenas_cpu_speed | GHz | |
| sensor.hdd_max_temperature | °C | |
| sensor.hdd_average_temperature | °C | |
| binary_sensor.truenas_system_naspool_healthy | on/off | Pool health. |
| sensor.system_monitor_processor_use | % | HA host CPU. |
| sensor.system_monitor_memory_usage | % | HA host RAM. |
| sensor.system_monitor_processor_temperature | °C | HA host temp. |
| sensor.system_monitor_load_15m | (none) | |
| sensor.backup_last_successful_automatic_backup | timestamp | Last backup. |
| sensor.backup_next_scheduled_automatic_backup | timestamp | Next backup. |
| update.* (pending updates) | on/off | Pending updates are the `update.*` entities with state `on`. Currently on: `update.file_editor_update`, `update.dobbyvision_update`. Filter by state `on`. |
| update.truenas_update | state | |

## Flagged: renamed or missing entities

These are referenced by a dashboard but do not exist in HA, so they show "Entity not found":

- `sensor.truenas_glances_cpu_usage`, `sensor.truenas_glances_tctl_temperature`, `sensor.truenas_glances_swap_usage`, `sensor.truenas_glances_containers_active`, `sensor.truenas_glances_containers_cpu_usage`, `sensor.truenas_glances_containers_memory_used` (Servers dashboard, NAS section). The working TrueNAS CPU sensor is `sensor.truenas_cpu_usage`.
- `sensor.rt_axe7800_connected_devices` (router connected devices).
- `sensor.sabnzbd_free_disk_space` (SABnzbd free space).
- `sensor.average_real_time_electricity` (Energy dashboard, not in use).
- `media_player.android_tv_192_168_1_229`, `media_player.bedroom_tv_2`, `switch.ozone_generator_plug_switch`.

Of 308 entity IDs referenced across all dashboards, 12 are missing. The Servers dashboard's "Entity not found" rows are the TrueNAS Glances entities above.

## Unavailable (exists but not reporting)

- `switch.heating`, `sensor.plants_humidity`, `binary_sensor.octopus_energy_a_<account>_octoplus_saving_sessions`, `binary_sensor.bedroom_th_sensor_battery_plus_low`, and several plant sensors. Do not rely on them for receipts.

## Not confirmed

- Rain chance is not in the current-state attributes. Use the `weather.get_forecasts` service.
- Whether each `history` is kept for every listed entity was inferred from `state_class`, not checked.
