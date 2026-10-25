# Briefings without a fixed print time

A briefing prints when Home Assistant releases it: on phone unplug in the morning, and on arriving home in the evening. Nobody sets a print time. Hermes queues the words ahead of time, and printarr fetches the live values when the paper comes out.

Placeholders: `<printarr-host>` is the printarr address (port 30100). `<recipient-a>` and `<recipient-b>` are the recipient ids `yannic` and `wife`, in either order.

## The flow

| When | Who | What |
|---|---|---|
| 04:00 each day | Hermes | Queues today's **morning** briefing for each recipient, `delivery: on_release`, `release_on: morning` (set from `time_of_day`), key `morning:<recipient>:<date>` |
| 06:00 each day | Hermes | Checks that today's morning briefing is still held. If not, queues it again with the same key |
| 15:00 each day | Hermes | Queues today's **evening** briefing for each recipient, `release_on: evening`, key `evening:<recipient>:<date>`, with the same check at 17:00 |
| Phone unplugged | Home Assistant | Releases that person's pile with `trigger: morning`: the `morning` and `any` tickets print, the evening briefing stays |
| Arriving home | Home Assistant | Releases that person's pile with `trigger: evening`: the `evening` and `any` tickets print |
| Morning or evening release, nothing queued for it | printarr | Builds the default briefing first, if one is set (see below) |

Queue time is not print time. A briefing waits in the person's pile until a release, so queueing at 04:00 does not print at 04:00. The fixed clock times only decide when the text is written.

Hermes does not need a webhook from Home Assistant. Each day's queue is keyed by its date, so a repeat call returns the ticket that already exists and prints nothing new. That makes the 06:00 and 17:00 checks safe to run every time.

## Your three questions, answered

**(a) When does Hermes queue the next one?** On a fixed daily job, not after each release. A released ticket is consumed, but tomorrow's key is new, so the 04:00 job always has something to queue. Two checks cover a missed run.

**(b) What if a trigger fires twice, or nothing is queued?**
- A second release on the same day prints only tickets that arrived since the first. The briefing was already consumed, so it does not print again.
- A release with an empty pile still prints the default briefing, if one is set and none was queued for that release. Once built, it is not built again that day, so a second release prints nothing new.
- With no default set and nothing queued, a release returns 200 with `"strips": []`. Nothing prints, and Home Assistant gets no error.

**(c) What if messages arrive after a release and before the next briefing?** They wait in the pile and print with the next release that matches their `release_on`. A message is `any` by default, so it prints at the next release of either kind. Nothing is lost.

## What printarr does now

- **Release tag per ticket.** Each held pile ticket has `release_on`: `morning`, `evening` or `any`. A briefing preset sets it from `time_of_day` (morning gives `morning`, afternoon or evening gives `evening`). A morning release prints the `morning` and `any` tickets; an evening or arrival release prints the `evening` and `any` tickets; a `request` prints the whole pile. So an early evening arrival no longer prints the morning briefing.
- **Default briefing.** printarr builds a standard briefing when a morning or evening release finds no briefing queued for it, if one is set. Set it once with `PUT /api/v1/briefing/default`: three `metrics` and a `graph` (the same shape as the preset, with no body and no fun fact). `GET` shows it and `DELETE` removes it. The values are read from Home Assistant when it prints. It is built at most once a day per person and release.
- **Home Assistant down at release.** The ticket still prints. A metric whose value cannot be read prints the placeholder `--` in place of its value, the layout stays put, and each failed read is logged. It does not page the owner; the ticket still prints.

### Still open

- **A stale briefing waits.** A morning briefing that was never released at the morning waits for the next morning release, because it is tagged for that release only. The owner asked for it to print on its own trigger, so it is not printed at an evening arrival.
- **The default needs its layout set.** Until `PUT /api/v1/briefing/default` is called, no default is built.
- **Text is fixed at queue time.** The body and fun fact are written when Hermes queues the briefing. Only the metrics, graph and sparklines are read at print time.

## 1. Message for Hermes

Send this to Hermes as it is, after replacing the placeholders:

```
From now on, set up printarr briefings like this. printarr is at http://<printarr-host>:30100.

1. Every day at 04:00 local time, for each recipient (<recipient-a> and <recipient-b>), queue today's morning briefing:
   POST /api/v1/tickets/compose with "preset": "briefing", "slots": {"time_of_day": "morning", ...},
   "kind": "morning", "delivery": "on_release", "idempotency_key": "morning:<recipient>:<YYYY-MM-DD>".
   Write the body and the fun fact for that day. Use entity_id for the three metrics and the graph, so the values are read when the paper prints.
   Use the full example in the printarr skill.
2. Every day at 15:00 local time, do the same for the evening briefing: time_of_day "evening", kind "evening", idempotency_key "evening:<recipient>:<YYYY-MM-DD>".
3. At 06:00 and 17:00, check GET /api/v1/tickets?status=held&recipient=<recipient>. If today's briefing is missing, queue it again with the same key. A repeat is safe.
4. Do not give any briefing a print time, and do not call POST /api/v1/people/{person}/release yourself. Home Assistant releases on phone unplug (morning) and on arriving home (evening).
5. Messages for a person use delivery "on_release". They print with the next release (release_on defaults to any).
6. Ping the owner with POST /api/v1/notify only when he needs to act.
```

## 2. Home Assistant YAML

Add the `rest_command` under `rest_command:` and the automations under `automation:` in `configuration.yaml`, or in a package. Replace `<printarr-host>`, the person entities and the two recipient ids.

```yaml
rest_command:
  printarr_release:
    url: "http://<printarr-host>:30100/api/v1/people/{{ person }}/release"
    method: POST
    content_type: "application/json"
    timeout: 30
    payload: '{"trigger": "{{ trigger }}"}'

automation:
  # Morning: the phone is unplugged, so release that person's morning briefing and waiting messages.
  - alias: "printarr: morning release on phone unplug"
    id: printarr_morning_unplug
    mode: queued
    trigger:
      - platform: state
        entity_id: binary_sensor.<person_a>_phone_charging
        from: "on"
        to: "off"
        id: person_a
      - platform: state
        entity_id: binary_sensor.<person_b>_phone_charging
        from: "on"
        to: "off"
        id: person_b
    action:
      - action: rest_command.printarr_release
        data:
          person: "{{ '<recipient-a>' if trigger.id == 'person_a' else '<recipient-b>' }}"
          trigger: morning
        continue_on_error: true

  # Evening: the person arrives home, so release their evening briefing and waiting messages.
  - alias: "printarr: evening release on arriving home"
    id: printarr_evening_arrival
    mode: queued
    trigger:
      - platform: state
        entity_id: "person.<person_a>"
        to: home
        id: person_a
      - platform: state
        entity_id: "person.<person_b>"
        to: home
        id: person_b
    action:
      - action: rest_command.printarr_release
        data:
          person: "{{ '<recipient-a>' if trigger.id == 'person_a' else '<recipient-b>' }}"
          trigger: evening
        continue_on_error: true
```

`trigger` accepts `morning`, `evening`, `arrival` or `request`. It is only written to the log, so `evening` on arrival is fine.

Note: `docs/integrations/home-assistant/automations.yaml` predates this flow. It builds the briefing when the phone is unplugged, with the older slot template, so it does not match the briefing preset. Use the YAML above instead.
