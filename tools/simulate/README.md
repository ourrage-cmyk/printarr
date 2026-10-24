# Simulation tools

Plays a simulated Hermes day against printarr and draws what the printer would print.
Run order and the server/laptop setup are in [`docs/deploy/simulation-v1.md`](../../docs/deploy/simulation-v1.md).

| File | What it does |
| --- | --- |
| `fake_ha.py` | A stand-in for Home Assistant's REST API (`/api/`, `/api/states/<id>`, history). Accepts only the simulation token. |
| `fixtures/ha_states.json` | Entity states the fake serves. Each entity has a simulated history wave. |
| `hermes_sim.py` | The scenario runner: briefings, messages, shopping, reminders, alerts, releases and bad requests. Writes PNGs and `manifest.json`. |
| `escpos_decode.py` | Decodes printarr's ESC/POS bytes (raster, text, cuts) and draws each strip to PNG. |

Quick start, everything local (printarr writes files instead of printing):

```bash
python tools/simulate/fake_ha.py --port 8123 &
PRINTARR_PRINTER_MODE=file PRINTARR_OUTPUT_DIR=/tmp/printarr-out PRINTARR_DB_PATH=/tmp/printarr.db \
  PRINTARR_LLM_ENABLED=off PRINTARR_SCHEDULER=off python -m uvicorn app.main:app --port 8000 &
# then set the Home Assistant URL http://127.0.0.1:8123 and token simulation-token-not-real in settings
python tools/simulate/hermes_sim.py --api http://localhost:8000 --bin-dir /tmp/printarr-out --out tools/simulate/out
```

Notes:

- The fake Home Assistant token is not a credential. Never give printarr the real token in these commands.
- Raster rows in the PNGs are exact. Text is drawn with a monospace font as an approximation of Font A; the simulator is the reference.
- `tools/simulate/out/` is git-ignored.
