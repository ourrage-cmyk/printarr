# Install, upgrade and roll back printarr on TrueNAS

Printarr runs as one app: the API, the web page and the ticket worker, in one container. You
install it from one YAML file. There is no env file and no second file.

## Before you start

1. **Create the data folder on your SSD dataset**, for example `/mnt/ssd/apps/printarr`.
2. **Give it to the app's user (uid 1000).** In the TrueNAS shell:
   ```sh
   mkdir -p /mnt/ssd/apps/printarr
   chown -R 1000:1000 /mnt/ssd/apps/printarr
   ```
   If the folder is not writable, the app stops at once and writes a message to its logs.
3. **Know the printer's IP address** (the Epson TM-T88V on the LAN, port 9100).
4. **Make sure the image is public** on GitHub (`ghcr.io/ourrage-cmyk/printarr`), so TrueNAS can
   pull it without a login.

## Install

1. In TrueNAS, go to **Apps > Discover Apps > Custom App** (on older releases,
   **Install Custom App**), and choose **Install via YAML**.
2. Paste the whole of [`docker-compose.yml`](../../docker-compose.yml) from the repository.
3. Change the two lines marked `<- change`: the printer's IP address, and the data folder if
   yours is different.
4. Save. Wait until the app shows **Running**.
5. Open `http://<nas-ip>:8000/` to write a ticket. To check the printer, print a test receipt with
   `curl -X POST http://<nas-ip>:8000/api/v1/printer/test`. It returns 502 if the printer is unreachable.

The data folder holds everything the app keeps: tickets, the saved settings (decision model,
Home Assistant, Telegram), the database and the backups. Keep it when you upgrade or remove the app.

## Check that it is healthy

- **Logs:** in TrueNAS, open the app and choose **Logs**. The first lines say which data folder
  and port are in use.
- **Smoke test** from any machine on the LAN, with the repository checked out:
  ```sh
  sh scripts/smoke-test.sh http://<nas-ip>:8000
  ```
  It creates one held ticket (it never prints), reads it back, and checks the backup export.
- **Health for Uptime Kuma:** `http://<nas-ip>:8000/api/v1/health`. It returns 200 when the
  database and printer are fine, and 503 when the printer is unplugged.

## Upgrade

The database upgrades itself on start, and a copy is taken first, so an upgrade does not lose
tickets or settings.

1. Note the current image tag (the `sha-` tag, shown on the app's **Edit** page).
2. Edit the app. Change the image tag to the new one. Use `latest` to follow main, or a
   `sha-...` tag to pin an exact build from the GitHub Actions run.
3. Save. TrueNAS pulls the new image and restarts the app.
4. Check the logs and run the smoke test.

Every time an older database is upgraded, the app first writes
`backups/pre-upgrade-v<n>-<time>.db` into the data folder. The last five are kept.

## Roll back

Use this if the new version misbehaves.

1. Edit the app and set the image tag back to the previous `sha-...` tag. Save.
2. If the new version already upgraded the database, the old version will refuse to start,
   and its log says the schema is too new. That is by design. Restore the copy taken just before
   the upgrade, as in the next section.

## Restore from a backup

Backups live in `<data folder>/backups/`:

- `nightly-<date>-<time>.db`: one a day at 03:00 local time, the last seven kept.
- `pre-upgrade-v<n>-<time>.db`: before each upgrade of the database.
- `pre-import-<time>.db`: the database as it was before a restore through the web API.

**Option A: restore through the API** (the app is running; no shell needed):

```sh
curl -X POST "http://<nas-ip>:8000/api/v1/backup/import?confirm=replace" \
     --data-binary @printarr-backup.db
```

Download a backup from the running app first with `GET /api/v1/backup/export`, or copy a file
from `backups/`. The current database is kept as `backups/pre-import-*.db`, so this can be undone.

**Option B: restore from the data folder** (the app is stopped):

1. Stop the app in TrueNAS.
2. In the TrueNAS shell, replace the database with the copy you want, and remove the journal files:
   ```sh
   cd /mnt/ssd/apps/printarr
   rm -f printarr.db-wal printarr.db-shm
   cp backups/<the-copy>.db printarr.db
   chown 1000:1000 printarr.db
   ```
3. Start the app.

Keep a copy of the current `printarr.db` before step 2 if you may want it back.

## Settings and the printer

- The decision model, Home Assistant and Telegram settings are saved in the database. Change
  them in the web page; they survive upgrades and rebuilds.
- `PRINTARR_PRINTER_HOST` in the YAML is the printer's address. To move from the simulator to
  the real printer, change this one line and save.
- Printer settings marked "first start only" in the YAML are read only on the first start.
  After that the web page wins.

## Nightly backups

- Turn them off with `PRINTARR_BACKUP: "off"`, or change the hour with `PRINTARR_BACKUP_HOUR`
  (0 to 23, local time), and how many to keep with `PRINTARR_BACKUP_KEEP`.
- Backups sit on the same SSD as the data. They protect against a bad upgrade or a damaged
  database, not against losing the SSD. Copy the `backups/` folder to another disk now and then.

## Resources and stopping

- The app is limited to 512 MB of memory and one CPU in the YAML. Raise `mem_limit` or `cpus` if
  the logs show it is starved.
- Stopping the app waits up to 30 seconds, so a ticket being printed can finish.

## Troubleshooting

| Symptom in the logs | Cause and fix |
| --- | --- |
| `data folder /data is not writable by uid 1000` | Run `chown -R 1000:1000` on the data folder, then restart. |
| `schema is version N, but this printarr supports up to M` | The data came from a newer version. Roll back the image, or restore the matching backup. |
| Health returns 503 | The printer is not reachable. Check the IP address, the printer's power and the LAN switch. |
| The web page loads but a ticket is `failed` | Open the ticket in the web page. Its `last_error` says why. |

## Development (laptop)

`docker-compose.dev.yml` runs printarr and the printer simulator as separate services, with the
data in `./dev-data`:

```sh
docker compose -f docker-compose.dev.yml up --build
```

## Test with the laptop standing in for the printer

Until the Epson arrives, the server can talk to the printer simulator on the laptop. The
server's printarr container sends raw ESC/POS to the laptop on TCP 9100, exactly as it would to
the TM-T88V. The simulator shows each receipt in a browser on the laptop.

**On the laptop (Windows, PowerShell):**

1. Start the simulator. It listens on TCP 9100 on all network interfaces, and its web page is on
   localhost only.
   ```powershell
   cd C:\CLAUDE\printer-simulator
   docker compose up -d --build
   Invoke-WebRequest http://localhost:8080/api/health
   ```
2. Find the laptop's LAN address. Use the IPv4 address of the adapter that is on the home network:
   ```powershell
   ipconfig
   ```
   Ask the router for a fixed (DHCP reservation) address for the laptop, so it does not change.
3. Allow inbound TCP 9100 through Windows Firewall on the private network. Run this once, as
   administrator. Check that the Wi-Fi or Ethernet network is set to **Private** first:
   ```powershell
   New-NetFirewallRule -DisplayName "Printer simulator 9100" -Direction Inbound -Protocol TCP -LocalPort 9100 -Action Allow -Profile Private
   ```
4. Keep the laptop awake while you test. If it sleeps, the server reports the printer as
   unreachable. Turn off sleep on AC power in Windows settings.

**On TrueNAS (shell), check the port is open before you start printarr:**

```sh
timeout 3 bash -c '</dev/tcp/<laptop-ip>/9100' && echo "port 9100 open" || echo "port 9100 closed"
```

**Install or update printarr with the laptop as the printer.** In the YAML from
[`docker-compose.yml`](../../docker-compose.yml), set:

```yaml
PRINTARR_PRINTER_MODE: tcp
PRINTARR_PRINTER_HOST: <laptop-ip>   # the laptop, for now
PRINTARR_PRINTER_PORT: "9100"
```

Save the app. Then check it, from any machine on the LAN:

```sh
curl http://<nas-ip>:8000/api/v1/printer                  # reachable: true
curl -X POST http://<nas-ip>:8000/api/v1/printer/test      # prints a test receipt
```

The receipt appears in the simulator at `http://localhost:8080` on the laptop. For the full
check, run `sh scripts/smoke-test.sh http://<nas-ip>:8000` as well.

**Monday, switch to the real printer.** Set `PRINTARR_PRINTER_HOST` to the TM-T88V's IP address
(give the printer a fixed address first) and save. Nothing else changes. Tickets, settings and
backups stay as they are.
