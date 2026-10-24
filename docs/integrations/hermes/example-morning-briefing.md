# Example: Hermes composes a morning briefing for Yannic

Values are illustrative. The flow matches the live API on main.

## Prompt given to Hermes

```
Compose Yannic's morning briefing for 26 October 2026. It should print at 07:00.

1. GET /api/v1/insights/entities?person=yannic&limit=12.
2. Pick three entities for the metrics. Prefer |z_score| above 2, a clear trend, or relevance 3.
   Give each a label of at most 20 characters and a unit. Pick one more numeric entity with history for the graph.
3. Write a body of three or four plain sentences and a one-line fun fact.
4. POST /api/v1/tickets/compose with preset briefing, recipient yannic, sender hermes,
   kind morning, delivery on_release, idempotency_key morning:yannic:2026-10-26.
5. Reply with the ticket id, and one line per metric on why it was chosen.
   Home Assistant prints it on Yannic's strip when his phone is unplugged.
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
  "recipient": "yannic",
  "sender": "hermes",
  "kind": "morning",
  "preset": "briefing",
  "delivery": "on_release",
  "idempotency_key": "morning:yannic:2026-10-26",
  "slots": {
    "time_of_day": "morning",
    "metrics": [
      {"label": "Sleep", "entity_id": "sensor.sleep_score", "hours": 168},
      {"label": "Steps", "entity_id": "sensor.total_steps", "unit": "steps", "hours": 168},
      {"label": "Body battery", "entity_id": "sensor.body_battery_most_recent", "unit": "%", "hours": 168}
    ],
    "graph": {"title": "Home temperature", "entity_id": "sensor.home_temperature", "hours": 24, "unit": "C"},
    "body": "Sleep came in low at 71, well below your usual 82, and steps are behind at 3,400 so far. Body battery is steady at 58. Home is a little cool at 18.6 degrees.",
    "fun_fact": "Honey does not spoil. Jars found in old tombs were still edible.",
    "from": "hermes"
  }
}
```

The headline is GOOD MORNING, from `time_of_day`. Every briefing has this same layout.

## What happens next

The briefing waits in Yannic's pile. When his phone is unplugged, Home Assistant creates the morning
briefing (same idempotency key, so it is not duplicated) and calls
`POST /api/v1/people/yannic/release` with `{"trigger": "morning"}`. His strip prints with the briefing
and any messages waiting for him, cut after each strip. the second person's strip is separate, and only prints
on her own trigger.
