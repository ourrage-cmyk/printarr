# Setup checklist for Yannic

Plain steps, in the order to do them. Each step says who does it. Most of it is already built.

## 1. Start printarr

- [ ] Yannic: open the printarr web UI and check the printer shows connected. If the printer is not on the network yet, the simulator stands in for it.
- [ ] Yannic: open `/api/v1/health` in a browser. It should say `"status": "ok"` for the database and the printer.

## 2. Connect Home Assistant

- [ ] Yannic: in Home Assistant, create a long-lived access token (Profile, then Security, then Long-lived access tokens).
- [ ] Yannic: paste the token into printarr, Settings, then Home Assistant. Also enter the Home Assistant URL. Printarr keeps the token. Do not put it in any file.
- [ ] Yannic: press "Test" next to Home Assistant. It should say reachable.

## 3. Add the printarr commands to Home Assistant

- [ ] Yannic: replace `PRINTARR_URL` with the printarr address in `rest_commands.yaml`, then paste it into `configuration.yaml`, or a package file.
- [ ] Yannic: paste `sensors.yaml`, `scripts.yaml` and `automations.yaml` the same way.
- [ ] Yannic: restart Home Assistant (or reload the YAML) and check there are no errors in the log.

## 4. Check the entity names

- [ ] Yannic: in Home Assistant, search for each `# CONFIRM` line in `automations.yaml`. Replace these with your real names:
  - `binary_sensor.yannic_pixel_is_charging` and `binary_sensor.allyson_pixel_is_charging` (phone charging)
  - `device_tracker.yannic_phone` and `device_tracker.allyson_phone` (home presence)
- [ ] Yannic: do the same for Allyson's phone entities.

## 5. Turn the automations on

- [ ] Yannic: start with the morning and evening automations. Unplug your phone in the morning (between 04:00 and 11:00) and check one strip prints.
- [ ] Yannic: arrive home after 16:00 and check the evening strip prints.
- [ ] Yannic: check that a second unplug or arrival the same day prints nothing extra.

## 6. Hermes

- [ ] Yannic: give Hermes the file `docs/integrations/hermes/openapi.yaml` as its tool definition, and `SKILL.md` as its instructions.
- [ ] Yannic: ask Hermes for a test note to Allyson. It should wait for her strip, not print now.

## 7. Things Yannic decides

- [ ] Which metrics appear on the briefing (Hermes chooses, you can override).
- [ ] Whether Allyson's strip uses the same tone defaults.
- [ ] Whether the printer should cut after each strip (the default) or once per day.

## If something goes wrong

- printarr log: `docker logs printarr` on the NAS.
- Home Assistant log: Settings, then System, then Logs, then search for `printarr`.
- A strip that did not print stays in the pile. Release it again with the release button in the web UI, or by calling `/api/v1/people/yannic/release`.
