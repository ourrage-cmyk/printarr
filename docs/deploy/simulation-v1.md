# Simulation v1: run printarr on the server, the printer on the laptop

This is the exact order to run a full day of simulated Hermes traffic. printarr runs on your
server with its real API and database. Your laptop plays the printer: the simulator listens on
raw TCP 9100 and draws what printarr sends. A fake Home Assistant on the laptop stands in for
the real one, so no real token is needed for the run.

Nothing here puts a real credential in a compose file, an environment variable or the repo.
Home Assistant settings are entered in the printarr web page, and only in the web page.

Time: about 30 minutes the first time.

## What you need

| Where | What |
| --- | --- |
| Server | Docker, and the printarr image (`ghcr.io/ourrage-cmyk/printarr`), or a checkout of this repo to build it |
| Laptop | The printer simulator (port 9100 raw TCP, page on 8080), Python 3.11 or newer, and a checkout of this repo |
| Network | Server and laptop on the same LAN. Laptop firewall allows inbound TCP 9100 and 8123 from the LAN |

Find the laptop's LAN address (Windows: `ipconfig`, the IPv4 address of the Wi-Fi or Ethernet
adapter). Below it is written as `LAPTOP_IP`, and the server address as `SERVER_IP`.

## 1. Laptop: start the simulator

Start the simulator so it listens on TCP 9100 (raw) and HTTP 8080 (its page).

- Check it draws: open `http://localhost:8080/` on the laptop.
- Check raw TCP from the server later with step 3.

## 2. Laptop: start the fake Home Assistant

```bash
cd printarr
python tools/simulate/fake_ha.py --host 0.0.0.0 --port 8123
```

It prints the simulation token. The token is not a real credential and only this fake server
accepts it. Leave this window open for the whole run.

## 3. Server: start printarr pointed at the laptop

Use [`docker-compose.yml`](../../docker-compose.yml) (the TrueNAS file) or a local compose file.
Change these lines only:

```yaml
PRINTARR_PRINTER_MODE: tcp
PRINTARR_PRINTER_HOST: LAPTOP_IP       # the laptop running the simulator
PRINTARR_PRINTER_PORT: "9100"
PRINTARR_LLM_ENABLED: "off"            # no decision model during the simulation
```

Start it, then check the link:

```bash
docker compose up -d
curl -s http://SERVER_IP:8000/api/v1/printer          # reachable: true
curl -s -X POST http://SERVER_IP:8000/api/v1/printer/test
```

The second call should print a test receipt on the laptop simulator. If it returns 502, the
laptop firewall or `PRINTARR_PRINTER_HOST` is the problem.

## 4. Server: point printarr at the fake Home Assistant

Open `http://SERVER_IP:8000/`, go to the Home Assistant settings and enter:

- URL: `http://LAPTOP_IP:8123`
- Access token: `simulation-token-not-real`

Press the test button. It should report reachable. Do not enter your real Home Assistant
address or token here until the simulation is finished (step 7).

## 5. Laptop: run the simulated Hermes day

From the repo folder on the laptop:

```bash
python tools/simulate/hermes_sim.py --api http://SERVER_IP:8000 --out tools/simulate/out
```

It does this, in order:

1. Morning: a briefing for you and one for Allyson, then the morning release for each person.
   Home Assistant would send these on the phone unplug.
2. Day: messages between you and Allyson in several moods, one raw speech message, a shopping
   list (printed at once), a reminder for 18:00, a water leak alert (printed at once), a fun fact,
   and a note.
3. Evening: the evening rundown is queued, then your arrival release prints your pile.
4. Mistakes: six bad requests, each must return 422 with a message that tells Hermes what to fix.
5. Standalone tickets (shopping, reminder, alert) are drawn to PNG from their bytes.

Expected last line: `N strip image(s) in tools/simulate/out; 0 unexpected failure(s)`.
Exit status 1 means at least one call failed unexpectedly. The full log is in
`tools/simulate/out/manifest.json`.

Each run needs empty piles. The script stops if a person still has held tickets. Restart
printarr on a fresh database (delete the `/data/printarr.db` file, or use a new data folder)
and run again. `--allow-existing` skips the check.

## 6. Read the output

- On the laptop simulator at `http://localhost:8080/`, each release strip and each standalone
  ticket is drawn as the printer receives it. This is the reference for text.
- In `tools/simulate/out/`, one PNG per strip, numbered in the order they were sent. These
  PNGs draw raster rows exactly and draw text with an approximate font, so judge text in the
  simulator, not in the PNG.

## 7. After the simulation

- Put your real Home Assistant address and token into the printarr web page (same settings
  place as step 4). Do not put them in a compose file or in this repo.
- Restart printarr on a fresh database before the real printer arrives, or keep the database
  if you want the simulation history in the log.
- Switch `PRINTARR_PRINTER_HOST` to the real printer's address and restart the service.
  Run `curl -X POST http://SERVER_IP:8000/api/v1/printer/test` and check the paper.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| `printer/test` returns 502 | Laptop simulator running, port 9100 open on the laptop firewall, `PRINTARR_PRINTER_HOST` is the laptop's address |
| Entity values show "data unavailable" | Fake HA running and reachable from the server (`curl http://LAPTOP_IP:8123/api/` with the simulation token), URL and token in the settings page |
| Harness says `printarr is not answering` | The `--api` address; from the laptop use the server's LAN address, not `localhost` |
| Harness says the piles are not empty | Restart printarr on a fresh database, see step 5 |
| Briefing has no graphs | Expected in v1: briefings print as text. See [the findings report](simulation-v1-findings.md) |
