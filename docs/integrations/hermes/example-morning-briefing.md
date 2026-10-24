# Example: Hermes composes a morning briefing for Yannic

Values are illustrative. The flow matches the live API on main.

## Prompt given to Hermes

```
Compose Yannic's morning briefing for 26 October 2026. It should print at 07:00.

1. GET /api/v1/templates/101/schema and check the slot limits.
2. GET /api/v1/insights/entities?person=yannic&limit=12.
3. Pick up to four entities. Prefer |z_score| above 2, a clear trend, or relevance 3.
   Give each a label of at most 20 characters and a unit.
4. Write a paragraph of three or four plain sentences and a one-line tip.
5. POST /api/v1/tickets/slots with template 101, recipient yannic, sender hermes,
   kind morning, send_at 2026-10-26T07:00:00.
6. Reply with the ticket id, and one line per metric on why it was chosen.
```

## Insights returned (trimmed)

```json
[
  {"entity_id": "sensor.sleep_score", "label": "Sleep score", "unit": "", "current": 71,
   "mean_30d": 82.4, "z_score": -2.1, "trend": "down", "trend_pct": -9.0, "relevance": 3,
   "why": "well outside the usual range"},
  {"entity_id": "sensor.total_steps", "label": "Steps", "unit": "steps", "current": 3400,
   "mean_30d": 8200, "z_score": -1.6, "trend": "down", "trend_pct": -18.0, "relevance": 3,
   "why": "below its usual level"},
  {"entity_id": "sensor.body_battery_most_recent", "label": "Body battery", "unit": "%",
   "current": 58, "mean_30d": 64.0, "z_score": -0.9, "trend": "flat", "trend_pct": 0.5,
   "relevance": 3, "why": "steady"},
  {"entity_id": "sensor.home_temperature", "label": "Home", "unit": "°C", "current": 18.6,
   "mean_30d": 19.8, "z_score": -1.4, "trend": "down", "trend_pct": -4.2, "relevance": 1,
   "why": "below its usual level"}
]
```

Hermes picks sleep score and steps (both unusual and own data), body battery (own data, for context),
and home temperature (shared, trending). It explains each choice in step 6.

## Payload Hermes sends

```json
{
  "template": 101,
  "recipient": "yannic",
  "sender": "hermes",
  "kind": "morning",
  "tone": "neutral",
  "send_at": "2026-10-26T07:00:00",
  "slots": {
    "title": "Morning",
    "metrics": [
      {"label": "SLEEP", "entity_id": "sensor.sleep_score", "hours": 168},
      {"label": "STEPS", "entity_id": "sensor.total_steps", "unit": "steps", "hours": 168},
      {"label": "BODY BATTERY", "entity_id": "sensor.body_battery_most_recent", "unit": "%", "hours": 168},
      {"label": "HOME", "entity_id": "sensor.home_temperature", "unit": "°C", "hours": 24}
    ],
    "paragraph": "Sleep came in low at 71, well below your usual 82, and steps are behind at 3,400 so far. Body battery is steady at 58. Home is a little cool at 18.6 degrees.",
    "tip": "A short walk before lunch would help the steps."
  }
}
```

Greeting is left out, so printarr writes "Good morning, Yannic" from the send time.

## Not yet accepted

Home Assistant releases this briefing when the phone is unplugged, which needs `hold`, `hold_key` and
`idempotency_key` on the slot endpoint. Those are requested from the API thread. Until then, use
`POST /tickets` with a plain `message`, `hold: true`, `hold_key: morning-yannic-2026-10-26` and
`idempotency_key: morning:yannic:2026-10-26`.
