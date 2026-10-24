"""Play a simulated Hermes agent against a running printarr, and draw what the printer would print.

Hermes is the only caller of the API in production. This script makes the same calls Hermes
makes (see docs/integrations/hermes/SKILL.md): briefings from /insights/entities, slot and
composed tickets, messages between the two people, shopping lists, timed reminders, alerts,
and the pile releases that Home Assistant triggers. It needs no real Home Assistant: point
printarr at tools/simulate/fake_ha.py instead.

Prerequisites (see docs/deploy/simulation-v1.md):
  * printarr running with PRINTARR_PRINTER_MODE=file and an output folder (--bin-dir below),
  * printarr's Home Assistant URL set to the fake HA, with the simulation token,
  * an empty pile for both people, so the release strips hold only this run's tickets.

    python tools/simulate/hermes_sim.py --api http://localhost:8000 \
        --bin-dir /path/to/printarr-output --out tools/simulate/out      # file mode, draws every strip
    python tools/simulate/hermes_sim.py --api http://server:8000 --out tools/simulate/out   # printer is a simulator

Writes one PNG per strip and a manifest.json with every call, its status and any 422 problems.
Exit status is 0 when every expected call succeeded, 1 when a call failed unexpectedly.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.simulate.escpos_decode import decode, render_png  # noqa: E402

DAY = "2026-10-24"
ENERGY_SERIES = [8.4, 8.1, 8.0, 8.6, 9.5, 10.2, 11.0, 11.8, 12.4, 13.1, 13.6, 14.0, 14.2, 13.9, 13.1, 12.6, 12.0, 11.4]


@dataclass
class Run:
    api: str
    bin_dir: Path | None
    out: Path
    calls: list[dict] = field(default_factory=list)
    pending: list[tuple[str, str, str]] = field(default_factory=list)  # (label, ticket id, delivery)
    rendered: list[dict] = field(default_factory=list)
    failures: int = 0
    counter: int = 0

    def request(self, method: str, path: str, body: dict | None = None, expect: int | None = None) -> tuple[int, object]:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.api + path, data=data, method=method, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                status, payload = resp.status, json.loads(resp.read() or b"null")
        except urllib.error.HTTPError as exc:
            status, payload = exc.code, json.loads(exc.read() or b"null")
        ok = status < 400 if expect is None else status == expect
        if not ok:
            self.failures += 1
        self.calls.append({"method": method, "path": path, "body": body, "status": status, "ok": ok, "response": payload})
        return status, payload

    def ticket(self, label: str, method: str, path: str, body: dict, expect: int = 201) -> str | None:
        status, payload = self.request(method, path, body, expect)
        if status != expect or not isinstance(payload, dict):
            print(f"  FAIL {label}: HTTP {status} {json.dumps(payload)[:300]}")
            return None
        ticket_id = payload["id"]
        print(f"  ok   {label}: {ticket_id[:8]} status={payload.get('status')} template={payload.get('template_id')}")
        self.pending.append((label, ticket_id, body.get("delivery") or "now"))
        return ticket_id

    def release(self, person: str, trigger: str) -> None:
        before = set(self.bin_dir.glob("*.bin")) if self.bin_dir else set()
        status, payload = self.request("POST", f"/people/{person}/release", {"trigger": trigger})
        new = sorted(set(self.bin_dir.glob("*.bin")) - before) if self.bin_dir else []
        if self.bin_dir is None:
            print(f"  release {person} ({trigger}): HTTP {status}, {len(payload.get('strips', [])) if isinstance(payload, dict) else 0} strip(s) sent to the printer")
        else:
            print(f"  release {person} ({trigger}): HTTP {status}, {len(new)} strip file(s)")
        for k, path in enumerate(new, 1):
            self.draw(path.read_bytes(), f"{self.counter:02d}-release-{person}-{trigger}-{k}")
        if status != 200:
            self.failures += 1

    def draw(self, data: bytes, name: str) -> None:
        self.counter += 1
        strips = decode(data)
        for index, strip in enumerate(strips, 1):
            suffix = "" if len(strips) == 1 else f"-{index}"
            target = self.out / f"{name}{suffix}.png"
            render_png(strip, target)
            print(f"       -> {target.name}: {'; '.join(strip.summary())}")
            self.rendered.append({"file": target.name, "items": strip.summary()})

    def draw_ticket(self, label: str, ticket_id: str) -> None:
        req = urllib.request.Request(f"{self.api}/tickets/{ticket_id}/escpos")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
        except urllib.error.HTTPError as exc:
            self.failures += 1
            print(f"  FAIL escpos for {label}: HTTP {exc.code}")
            return
        self.draw(data, f"{self.counter:02d}-{label}")

    def insights(self, person: str) -> list[dict]:
        _, rows = self.request("GET", f"/insights/entities?person={person}&limit=12")
        return rows if isinstance(rows, list) else []


def pick_metrics(rows: list[dict], count: int) -> list[dict]:
    """Hermes rule: unusual first (z above 2 or below -2), then trending, then relevance 3."""
    ranked = sorted(rows, key=lambda r: (abs(r.get("z_score", 0)) > 2, r.get("trend") != "flat", r.get("relevance", 0)), reverse=True)
    chosen, seen = [], set()
    for row in ranked:
        if row["label"] in seen:
            continue
        seen.add(row["label"])
        chosen.append({"label": row["label"][:20], "entity_id": row["entity_id"], "unit": row["unit"] or None, "hours": 24})
        if len(chosen) == count:
            break
    return chosen


def scenario(run: Run) -> None:
    print("1. Morning: briefings, then the morning release (Home Assistant unplugs the phone)")
    yannic_metrics = pick_metrics(run.insights("yannic"), 3) + [{"label": "Energy", "value": 0.079, "unit": "GBP/kWh"}]
    run.ticket("briefing-yannic", "POST", "/tickets/slots", {
        "template": 101, "recipient": "yannic", "sender": "hermes", "delivery": "on_release",
        "idempotency_key": f"morning:yannic:{DAY}",
        "slots": {
            "greeting": "Good morning, Yannic",
            "title": "Today",
            "metrics": yannic_metrics,
            "paragraph": "Body battery is 54 percent, below its usual level for this time. Steps are ahead of your average. Energy is cheap until 16:00.",
            "tip": "Leave five minutes early, the lights are on a timer.",
        },
    })
    wife_metrics = pick_metrics(run.insights("wife"), 2) + [{"label": "Home", "entity_id": "sensor.home_temperature", "unit": "C", "hours": 24}]
    run.ticket("briefing-wife", "POST", "/tickets/slots", {
        "template": 101, "recipient": "wife", "sender": "hermes", "delivery": "on_release",
        "idempotency_key": f"morning:wife:{DAY}",
        "slots": {
            "greeting": "Good morning, Allyson",
            "title": "Today",
            "metrics": wife_metrics,
            "paragraph": "Sleep was steady and the house is at a comfortable 19.5 degrees.",
        },
    })
    run.release("yannic", "morning")
    run.release("wife", "morning")

    print("2. Day: messages between the two people, in several moods, plus one raw speech message")
    messages = [
        ("wife", "yannic", "happy", "The bins are out and the dogs are fed. Have a lovely day.", "Allyson"),
        ("wife", "yannic", "sad", "I missed you at lunch today. Call me when you are free.", "Allyson"),
        ("wife", "yannic", "excited", "Guess what, the garden table has arrived!", "Allyson"),
        ("wife", "yannic", "confused", "Where did the spare keys go? I cannot find them anywhere.", "Allyson"),
        ("yannic", "wife", "loving", "Thank you for the cookies. I love you so much.", "Yannic"),
        ("yannic", "wife", "gentle_warning", "Please do not leave the back door open again, the heating is on.", "Yannic"),
        ("wife", "yannic", "auto", "A long message that goes over several lines so that the wrapping of the paragraph can be checked, with a tip at the bottom.", "Allyson"),
    ]
    for k, (src, dst, mood, text, sign) in enumerate(messages, 1):
        run.ticket(f"msg-{src}-to-{dst}-{mood}", "POST", "/tickets/compose", {
            "recipient": dst, "from_user": src, "to_user": dst, "sender": "hermes", "kind": "note",
            "delivery": "on_release", "tone": "loving" if mood == "loving" else "neutral",
            "idempotency_key": f"msg:{DAY}:{k}",
            "blocks": [{"type": "message", "mood": mood, "slots": {"paragraph": text, "from": sign}}],
        })
    run.ticket("msg-raw-speech", "POST", "/tickets", {
        "recipient": "yannic", "sender": "hermes", "from_user": "wife", "to_user": "yannic",
        "title": "Plumber", "message": "um so tell yannic the uh plumber is coming tuesday between nine and eleven",
        "text_state": "unformatted", "delivery": "on_release",
    }, expect=201)

    run.ticket("shopping-list", "POST", "/tickets/compose", {
        "recipient": "yannic", "from_user": "wife", "to_user": "yannic", "sender": "hermes", "kind": "shopping",
        "delivery": "now",
        "blocks": [
            {"type": "checklist", "mood": "neutral", "slots": {"title": "Shopping", "items": [
                {"text": "Oat milk"}, {"text": "Dog food, 2 bags"}, {"text": "Bread"}, {"text": "Eggs x6", "checked": True}]}},
            {"type": "tip", "mood": "reminder", "slots": {"tip": "Bin bags are under the sink."}},
        ],
    })
    run.ticket("reminder-at-18", "POST", "/tickets/compose", {
        "recipient": "wife", "sender": "hermes", "kind": "reminder", "delivery": "at", "send_at": f"{DAY}T18:00:00",
        "blocks": [{"type": "tip", "mood": "reminder", "slots": {"tip": "Pick up the parcel before 18:30."}}],
    })
    run.ticket("alert-water-leak", "POST", "/tickets/compose", {
        "recipient": "yannic", "sender": "hermes", "kind": "alert", "delivery": "now",
        "blocks": [{"type": "alert", "mood": "urgent", "slots": {
            "label": "WATER LEAK", "paragraph": "Water is coming through under the kitchen sink. Turn off the stopcock now.", "action": "Stopcock"}}],
    })
    run.ticket("fact-for-wife", "POST", "/tickets/compose", {
        "recipient": "wife", "sender": "hermes", "kind": "fun", "delivery": "on_release",
        "blocks": [{"type": "fact", "mood": "playful", "slots": {"paragraph": "Octopuses have three hearts and blue blood."}}],
    })
    run.ticket("note-102", "POST", "/tickets/slots", {
        "template": 102, "recipient": "yannic", "sender": "hermes", "delivery": "on_release",
        "slots": {"title": "Parcel", "paragraph": "The parcel for the garden table is due at the depot on Monday.", "tip": "Bring the car keys."},
    })

    print("3. Evening: the rundown is queued, then the arrival release prints Yannic's pile")
    run.ticket("evening-rundown-yannic", "POST", "/tickets/compose", {
        "recipient": "yannic", "sender": "hermes", "kind": "evening", "delivery": "on_release",
        "idempotency_key": f"evening:yannic:{DAY}",
        "blocks": [
            {"type": "greeting", "mood": "happy", "slots": {"greeting": "Welcome home, Yannic", "summary": "Here is the evening."}},
            {"type": "dog_counts", "mood": "neutral", "slots": {"dogs": [
                {"name": "Bridget", "pee": 5, "poop": 1, "food": 2, "run": 0},
                {"name": "Kida", "pee": 4, "poop": 2, "food": 2, "run": 1}]}},
            {"type": "metric_rows", "mood": "factual", "slots": {"title": "Today", "rows": [
                {"label": "Steps", "entity_id": "sensor.total_steps"},
                {"label": "Energy now", "entity_id": "sensor.realtime_energy_cost", "unit": "GBP/h"}]}},
            {"type": "tip", "mood": "reminder", "slots": {"tip": "Bins go out tomorrow."}},
        ],
    })
    run.ticket("graph-energy-yannic", "POST", "/tickets/compose", {
        "recipient": "yannic", "sender": "hermes", "delivery": "on_release",
        "blocks": [{"type": "graph", "mood": "factual", "slots": {"title": "Energy price, 18 h", "series": ENERGY_SERIES, "unit": "p"}}],
    })
    run.release("yannic", "arrival")
    run.release("wife", "request")

    print("4. Mistakes Hermes might make: each must return 422 with a message that says how to fix it")
    probes = [
        ("unknown block type", "/tickets/compose", {"recipient": "yannic", "blocks": [{"type": "confetti", "slots": {}}]}),
        ("metric without a value or entity", "/tickets/compose", {"recipient": "yannic", "blocks": [
            {"type": "metric_rows", "mood": "factual", "slots": {"rows": [{"label": "Steps"}]}}]}),
        ("unknown mood", "/tickets/compose", {"recipient": "yannic", "blocks": [
            {"type": "tip", "mood": "sleepy", "slots": {"tip": "Night"}}]}),
        ("slot template with a missing paragraph", "/tickets/slots", {"template": 102, "recipient": "wife", "slots": {"title": "Hi"}}),
        ("not a slot template", "/tickets/slots", {"template": 999, "recipient": "wife", "slots": {}}),
        ("unknown recipient", "/tickets", {"recipient": "dog", "message": "Walk"}),
    ]
    for label, path, body in probes:
        status, payload = run.request("POST", path, body, expect=422)
        detail = payload.get("detail") if isinstance(payload, dict) else payload
        print(f"  {'ok  ' if status == 422 else 'FAIL'} {label}: HTTP {status} {json.dumps(detail)[:220]}")

    print("5. Standalone tickets (now and at) drawn from their ESC/POS bytes; pile tickets were drawn in their strips")
    for label, ticket_id, delivery in run.pending:
        if delivery in ("now", "at"):
            run.draw_ticket(label, ticket_id)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--bin-dir", type=Path, default=None,
                        help="printarr's file output folder (PRINTARR_OUTPUT_DIR). Omit when printarr sends to a real simulator: "
                             "release strips are then drawn by the simulator, and standalone tickets still come out as PNG.")
    parser.add_argument("--out", type=Path, default=Path(__file__).with_name("out"))
    parser.add_argument("--allow-existing", action="store_true", help="run even when a pile already holds tickets")
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    if args.bin_dir is None:
        print("note: no --bin-dir, so release strips are not drawn here; read them in the simulator")
    run = Run(api=args.api.rstrip("/") + "/api/v1", bin_dir=args.bin_dir, out=args.out)
    status, _ = run.request("GET", "/health")
    if status not in (200, 503):  # 503 means the printer is down, which is fine in file mode
        print(f"printarr is not answering at {args.api}: HTTP {status}")
        sys.exit(1)
    waiting = {}
    for person in ("yannic", "wife"):
        _, rows = run.request("GET", f"/tickets?recipient={person}&status=held&limit=200")
        waiting[person] = len(rows) if isinstance(rows, list) else 0
    if any(waiting.values()) and not args.allow_existing:
        print(f"the piles are not empty (held tickets: {waiting}). Restart printarr on a fresh database, or pass --allow-existing.")
        sys.exit(1)
    scenario(run)
    manifest = {"calls": run.calls, "rendered": run.rendered, "failures": run.failures}  # noqa: E501
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    print(f"\n{len(run.rendered)} strip image(s) in {args.out}; {run.failures} unexpected failure(s)")
    sys.exit(1 if run.failures else 0)


if __name__ == "__main__":
    main()
