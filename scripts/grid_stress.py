"""Renders grid cases through the simulator, to check cut-off, overlap and fit by eye.

Usage: python scripts/grid_stress.py [outdir] [simulator-url]
"""

from __future__ import annotations

import base64
import json
import sys
import urllib.request
from pathlib import Path

from app.escpos import encode
from app.receipt import Line
from app.render.strips import Block, layout, render_strip_with_notes, split_strips

OUTDIR = Path(sys.argv[1] if len(sys.argv) > 1 else "renders_grid")
SIM = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8080"

WORD = "lorem ipsum dolor sit amet consectetur adipiscing elit "


def text(words: int) -> str:
    return (WORD * (words // 8 + 1)).split()[: words]


def sentence(words: int) -> str:
    return " ".join(text(words))


CASES: dict[str, list[Block]] = {
    "msg-short": [Block("message", {"paragraph": sentence(5), "from": "Yannic"}, "loving")],
    "msg-medium": [Block("message", {"paragraph": sentence(30), "from": "Yannic"}, "neutral")],
    "msg-long": [Block("message", {"paragraph": sentence(90), "from": "Yannic"}, "reminder")],
    "msg-overflow": [Block("message", {"paragraph": sentence(400), "from": "Yannic"}, "firm_complaint")],
    "metric-1": [Block("metric", {"label": "Body battery", "value": 72, "unit": "%"}, "factual")],
    "metric-3": [
        Block("metric", {"label": "Body battery", "value": 72, "unit": "%", "series": [60, 65, 70, 72]}, "factual"),
        Block("metric", {"label": "Steps", "value": "6,120"}, "factual"),
        Block("metric", {"label": "Stress", "value": 24}, "factual"),
    ],
    "metric-plus-message": [
        Block("metric", {"label": "Battery", "value": 72, "unit": "%"}, "factual"),
        Block("message", {"paragraph": sentence(12), "from": "Yannic"}, "neutral", span=2),
    ],
    "message-plus-metric": [
        Block("message", {"paragraph": sentence(12), "from": "Yannic"}, "neutral", span=2),
        Block("metric", {"label": "Battery", "value": 72, "unit": "%"}, "factual"),
    ],
    "graph-short": [Block("graph", {"title": "Outside", "series": [8, 9, 12], "unit": "C"})],
    "graph-long": [Block("graph", {"title": "Outside, 24 h", "series": [8.4, 8.1, 8.0, 8.6, 9.5, 10.2, 11.0, 11.8, 12.4, 13.1, 13.6, 14.0, 14.2, 13.9, 13.1, 12.6, 12.0, 11.4, 10.9, 10.4, 10.0, 9.6, 9.2, 8.9], "unit": "C"})],
    "rows-6": [Block("metric_rows", {"title": "Energy", "rows": [{"label": f"Row {i}", "value": i * 3, "unit": "GBP"} for i in range(6)]}, "factual")],
    "check-3": [Block("checklist", {"title": "Shopping", "items": [{"text": "Milk"}, {"text": "Eggs", "checked": True}, {"text": "Bread"}]})],
    "check-10": [Block("checklist", {"title": "Shopping", "items": [{"text": f"Item {i}"} for i in range(10)]})],
    "alert-long": [Block("alert", {"label": "Water leak", "paragraph": sentence(60), "action": "Stopcock"}, "urgent")],
    "tip-long": [Block("tip", {"tip": sentence(40)}, "reminder")],
    "fact-long": [Block("fact", {"paragraph": sentence(70)}, "playful")],
    "greeting-long": [Block("greeting", {"greeting": "Good morning, Yannic", "summary": sentence(60)}, "neutral")],
    "briefing-full": [
        Block("greeting", {"greeting": "Good morning, Yannic", "summary": "Cloudy, 12 C, rain after 3pm."}),
        Block("metric", {"label": "Body battery", "value": 72, "unit": "%", "series": [60, 65, 70, 72]}, "factual"),
        Block("metric", {"label": "Steps", "value": "6,120"}, "factual"),
        Block("graph", {"title": "Outside, 24 h", "series": [8.4, 9.5, 12.4, 14.2, 8.9], "unit": "C"}),
        Block("dog_counts", {"dogs": [{"name": "Bridget", "pee": 3, "poop": 1, "food": 2, "run": 1}]}),
    ],
}


def simulate(data: bytes) -> dict:
    req = urllib.request.Request(f"{SIM}/api/simulate?format=json", data=data, headers={"Content-Type": "application/octet-stream"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as res:
        return json.loads(res.read())


def main() -> None:
    OUTDIR.mkdir(parents=True, exist_ok=True)
    report = []
    for name, blocks in CASES.items():
        for i, strip in enumerate(split_strips(blocks)):
            bitmap, notes = render_strip_with_notes(strip)
            rows, _ = layout(strip)
            data = encode([Line(text="", raster=(bitmap.width // 8, bitmap.height, bitmap.bits))], feed=1)
            ticket = next(t for t in simulate(data)["tickets"] if t.get("png"))
            label = f"{name}-{i + 1}" if len(split_strips(blocks)) > 1 else name
            (OUTDIR / f"{label}.png").write_bytes(base64.b64decode(ticket["png"].split(",", 1)[1]))
            units = [[p.units for p in row] for row in rows]
            report.append({"name": label, "rows": units, "height": bitmap.height, "notes": notes})
            print(f"{label}: {bitmap.height}px, rows {units}, notes {notes}")
    (OUTDIR / "report.json").write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
