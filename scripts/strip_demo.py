"""Renders sample strips with the block renderer and sends them to the simulator.

Usage: python scripts/strip_demo.py [outdir] [simulator-url]
Each strip is encoded as the printer's raster command, so the simulator draws what the printer gets.
"""

from __future__ import annotations

import base64
import json
import sys
import urllib.request
from pathlib import Path

from app.escpos import encode
from app.receipt import Line
from app.render.strips import Block, MOODS, render_strip, split_strips

OUTDIR = Path(sys.argv[1] if len(sys.argv) > 1 else "renders_py")
SIM = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8080"
OUTSIDE = [8.4, 8.1, 8.0, 8.6, 9.5, 10.2, 11.0, 11.8, 12.4, 13.1, 13.6, 14.0, 14.2, 13.9, 13.1, 12.6, 12.0, 11.4, 10.9, 10.4, 10.0, 9.6, 9.2, 8.9]
MOOD_TEXT = "The bin lorry came early today, so the blue bin is already out front."

MORNING = [
    Block("greeting", {"greeting": "Good morning, Yannic", "summary": "Cloudy, 12 C, rain after 3pm. Cheap energy until 16:00."}),
    Block("metric", {"label": "Body battery", "value": 72, "unit": "%"}, "factual"),
    Block("metric", {"label": "Steps", "value": "6,120"}, "factual"),
    Block("metric_rows", {"title": "Energy and house", "rows": [{"label": "Energy now", "value": "0.079", "unit": "GBP/kWh"}, {"label": "Energy 16:00", "value": "0.245", "unit": "GBP/kWh"}, {"label": "Inside / out", "value": "19.5 / 12", "unit": "C"}]}, "factual"),
    Block("graph", {"title": "Outside, 24 h", "series": OUTSIDE, "unit": "C"}, "factual"),
    Block("dog_counts", {"dogs": [{"name": "Bridget", "pee": 3, "poop": 1, "food": 2, "run": 1}, {"name": "Kida", "pee": 2, "poop": 2, "food": 2, "run": 2}]}),
]
EVENING = [
    Block("greeting", {"greeting": "Good evening, Allyson", "summary": "Welcome back. Here is the day."}, "happy"),
    Block("dog_counts", {"dogs": [{"name": "Bridget", "pee": 5, "poop": 1, "food": 2, "run": 0}]}),
    Block("metric_rows", {"title": "Today", "rows": [{"label": "Steps", "value": "8,430"}, {"label": "Saved", "value": "0.42", "unit": "GBP"}]}, "factual"),
    Block("message", {"paragraph": "Thank you for the coffee this morning. It made the whole day easier. Love you.", "from": "Yannic"}, "loving"),
    Block("tip", {"tip": "Check the bins before you leave tomorrow."}, "reminder"),
]
ALERT = [Block("alert", {"label": "Water leak", "paragraph": "Water leak under the kitchen sink. Turn off the stopcock now.", "action": "Stopcock"}, "urgent")]
SHOPPING = [
    Block("checklist", {"title": "Shopping", "items": [{"text": "Milk (oat)"}, {"text": "Dog food, 2 bags"}, {"text": "Bread"}, {"text": "Eggs x6", "checked": True}]}),
    Block("tip", {"tip": "Bin bags are in the cupboard under the sink."}),
]
TODO = [Block("checklist", {"title": "To do", "items": [{"text": "Bins out"}, {"text": "Dentist 14:30 Fri"}, {"text": "Call bank"}]}, "reminder")]
GALLERY = [Block("message", {"title": mood, "paragraph": MOOD_TEXT, "from": "Yannic"}, mood) for mood in MOODS]

STRIPS = {
    "morning-briefing": MORNING,
    "evening-rundown": EVENING,
    "alert-urgent": ALERT,
    "shopping": SHOPPING,
    "to-do": TODO,
    **{f"mood-gallery-{i + 1}": s for i, s in enumerate(split_strips(GALLERY))},
}


def simulate(data: bytes) -> dict:
    req = urllib.request.Request(
        f"{SIM}/api/simulate?format=json",
        data=data,
        headers={"Content-Type": "application/octet-stream"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as res:
        return json.loads(res.read())


def main() -> None:
    OUTDIR.mkdir(parents=True, exist_ok=True)
    report = []
    for name, blocks in STRIPS.items():
        bitmap = render_strip(blocks)
        # One raster line, then the feed and partial cut: the same bytes printarr sends for an image ticket.
        data = encode([Line(text="", raster=(bitmap.width // 8, bitmap.height, bitmap.bits))], feed=1)
        body = simulate(data)
        ticket = next(t for t in body["tickets"] if t.get("png"))
        (OUTDIR / f"{name}.png").write_bytes(base64.b64decode(ticket["png"].split(",", 1)[1]))
        (OUTDIR / f"{name}.bin").write_bytes(data)
        report.append({"name": name, "blocks": [f"{b.type}:{b.mood}" for b in blocks], "width": ticket["width"], "height": ticket["height"]})
        print(f"{name}: {ticket['width']}x{ticket['height']}, {len(blocks)} blocks")
    (OUTDIR / "strips.json").write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
