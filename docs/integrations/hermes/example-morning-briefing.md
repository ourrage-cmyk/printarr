# Example: Hermes composes a morning briefing for Yannic

This shows the flow for one briefing. The prompt is what Hermes is given. The payload is what it
sends. Values are illustrative.

## Prompt given to Hermes

```
Compose Yannic's morning briefing for 26 October 2026, local time 06:40.

1. Call GET /api/v1/insights/entities?person=yannic&limit=12.
2. Pick four entities. Prefer unusual values (|z_score| above 1.5), a clear trend, or
   relevance 3. Give each a short label and say why you chose it.
3. Write a greeting for the time of day, a one-sentence title, a paragraph of three to
   four sentences, and a one-line tip.
4. Send it with POST /api/v1/tickets: recipient yannic, sender hermes, kind morning,
   tone neutral, hold true, hold_key morning-yannic-2026-10-26,
   idempotency_key morning:yannic:2026-10-26.
5. Reply with the ticket id and the four entities you chose, with one line each on why.
```

## Insights returned (trimmed)

```json
[
  {"entity_id": "sensor.sleep_score", "label": "Sleep score", "unit": "", "current": 71,
   "mean_30d": 82.4, "z_score": -2.1, "trend": "down", "trend_pct": -9.0, "relevance": 3,
   "why": "well outside the usual range"},
  {"entity_id": "sensor.body_battery_most_recent", "label": "Body battery", "unit": "%",
   "current": 58, "mean_30d": 64.0, "z_score": -0.9, "trend": "flat", "trend_pct": 0.5,
   "relevance": 3, "why": "steady"},
  {"entity_id": "sensor.home_temperature", "label": "Home", "unit": "°C", "current": 18.6,
   "mean_30d": 19.8, "z_score": -1.4, "trend": "down", "trend_pct": -4.2, "relevance": 1,
   "why": "below its usual level"},
  {"entity_id": "sensor.total_steps", "label": "Steps", "unit": "steps", "current": 3400,
   "mean_30d": 8200, "z_score": -1.6, "trend": "down", "trend_pct": -18.0, "relevance": 3,
   "why": "below its usual level"}
]
```

## Payload Hermes sends (current API)

Until the slot schema ships, the four metrics go in `blocks`, and the rest goes in `message`.
Blocks are read at print time, so the graph is current when the ticket prints.

```json
{
  "recipient": "yannic",
  "sender": "hermes",
  "kind": "morning",
  "tone": "neutral",
  "title": "Morning",
  "message": "Good morning, Yannic.\n\nSleep came in low at 71, well below your usual 82, and body battery is a little under par at 58. Home is cooler than usual at 18.6 degrees, and you are behind on steps today with 3,400 so far. A quieter start might suit you.\n\nTip: a short walk before lunch would help the steps.",
  "template": "auto",
  "hold": true,
  "hold_key": "morning-yannic-2026-10-26",
  "idempotency_key": "morning:yannic:2026-10-26",
  "blocks": [
    {"type": "value", "entity_id": "sensor.sleep_score", "label": "Sleep score"},
    {"type": "sparkline", "entity_id": "sensor.body_battery_most_recent", "label": "Body battery", "hours": 168},
    {"type": "value", "entity_id": "sensor.home_temperature", "label": "Home", "unit": "°C"},
    {"type": "sparkline", "entity_id": "sensor.total_steps", "label": "Steps", "hours": 168}
  ]
}
```

## Target payload (once API-core ships slots)

The same briefing in the slot shape. `slots` is not accepted by the API yet.

```json
{
  "recipient": "yannic",
  "sender": "hermes",
  "kind": "morning",
  "template": "auto",
  "hold": true,
  "hold_key": "morning-yannic-2026-10-26",
  "idempotency_key": "morning:yannic:2026-10-26",
  "slots": {
    "greeting": "Good morning, Yannic.",
    "title": "Morning",
    "metrics": [
      {"entity_id": "sensor.sleep_score", "label": "Sleep", "hours": 168},
      {"entity_id": "sensor.body_battery_most_recent", "label": "Body battery", "unit": "%", "hours": 168},
      {"entity_id": "sensor.home_temperature", "label": "Home", "unit": "°C", "hours": 24},
      {"entity_id": "sensor.total_steps", "label": "Steps", "hours": 168}
    ],
    "paragraph": "Sleep came in low at 71, well below your usual 82. Body battery is a little under par, and you are behind on steps. A quieter start might suit you.",
    "tip": "A short walk before lunch would help the steps."
  }
}
```
