# Setup checklist for the owner

Plain steps, in the order to do them. Each step says who does it. Most of it is already built.

## 1. Start printarr

- [ ] the owner: open the printarr web UI and check the printer shows connected. If the printer is not on the network yet, the simulator stands in for it.
- [ ] the owner: open `/api/v1/health` in a browser. It should say `"status": "ok"` for the database and the printer.

## 2. Connect Home Assistant

- [ ] the owner: in Home Assistant, create a long-lived access token (Profile, then Security, then Long-lived access tokens).
- [ ] the owner: paste the token into printarr, Settings, then Home Assistant. Also enter the Home Assistant URL. Printarr keeps the token. Do not put it in any file.
- [ ] the owner: press "Test" next to Home Assistant. It should say reachable.

## 3. Add the printarr commands to Home Assistant

- [ ] the owner: replace `PRINTARR_URL` with the printarr address in `rest_commands.yaml`, then paste it into `configuration.yaml`, or a package file.
- [ ] the owner: paste `sensors.yaml`, `scripts.yaml` and `automations.yaml` the same way.
- [ ] the owner: restart Home Assistant (or reload the YAML) and check there are no errors in the log.

## 4. Check the entity names

- [ ] the owner: in Home Assistant, search for each `# CONFIRM` line in `automations.yaml`. Replace these with your real names:
  - `binary_sensor.yannic_pixel_is_charging` and `binary_sensor.allyson_pixel_is_charging` (phone charging)
  - `device_tracker.yannic_phone` and `device_tracker.allyson_phone` (home presence)
- [ ] the owner: do the same for the second person's phone entities.

## 5. Turn the automations on

- [ ] the owner: start with the morning and evening automations. Unplug your phone in the morning (between 04:00 and 11:00) and check one strip prints.
- [ ] the owner: arrive home after 16:00 and check the evening strip prints.
- [ ] the owner: check that a second unplug or arrival the same day prints nothing extra.

## 6. Hermes

- [ ] the owner: give Hermes the file `docs/integrations/hermes/openapi.yaml` as its tool definition, and `SKILL.md` as its instructions.
- [ ] the owner: ask Hermes for a test note to the second person. It should wait for her strip, not print now.

## 7. Things the owner decides

- [ ] Which metrics appear on the briefing (Hermes chooses, you can override).
- [ ] Whether the second person's strip uses the same tone defaults.
- [ ] Whether the printer should cut after each strip (the default) or once per day.

## If something goes wrong

- printarr log: `docker logs printarr` on the NAS.
- Home Assistant log: Settings, then System, then Logs, then search for `printarr`.
- A strip that did not print stays in the pile. Release it again with the release button in the web UI, or by calling `/api/v1/people/yannic/release`.
