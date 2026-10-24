"""Check which template the decision model picks for plain-text tickets (no template given).

Usage: python tools/classify_check.py [base_url]
Posts each case in tests/classifier_cases.json to POST /api/v1/tickets/preview, which chooses
a template and renders without printing or queueing. Prints accuracy per category and every miss.
Needs only the standard library. Run it where the printarr server is reachable.
"""

import json
import pathlib
import sys
import urllib.request
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.templates import TEMPLATES  # noqa: E402  (kind of each template id)

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
CASES = json.loads((ROOT / "tests" / "classifier_cases.json").read_text())
KIND_OF = {t.id: t.kind for t in TEMPLATES}


def preview(recipient: str, message: str) -> dict:
    body = json.dumps({"recipient": recipient, "message": message, "template": "auto"}).encode()
    request = urllib.request.Request(
        f"{BASE}/api/v1/tickets/preview", data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.loads(response.read())


def main() -> None:
    right, total = Counter(), Counter()
    misses = []
    for case in CASES:
        expected = case["category"]
        try:
            out = preview(case["recipient"], case["message"])
        except Exception as exc:  # report and keep going
            misses.append((case, f"ERROR {exc}"))
            total[expected] += 1
            continue
        got_kind = KIND_OF.get(out["template_id"], "?")
        total[expected] += 1
        # "note" also covers plain tickets; a fun fact or reminder is a note in this classifier.
        ok = got_kind == expected or (expected == "note" and got_kind in ("note", "plain"))
        if ok:
            right[expected] += 1
        else:
            misses.append((case, f"{out['template_id']} kind={got_kind} via {out['selection']}"))
    for category in total:
        print(f"{category:8} {right[category]}/{total[category]}")
    print(f"total    {sum(right.values())}/{sum(total.values())}")
    for case, got in misses:
        print(f"MISS {case['recipient']:7} want={case['category']:8} got={got} :: {case['message']}")


if __name__ == "__main__":
    main()
