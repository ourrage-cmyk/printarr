# Install, upgrade and roll back printarr on TrueNAS

Printarr runs as one app: the API, the web page and the ticket worker, in one container. You
install it from one YAML file. There is no env file and no second file.

## Before you start

1. **Create the data folder on your SSD dataset**, for example `/mnt/pool/printarr`. Everything
   printarr keeps lives in this one folder: the database (tickets, settings, the setup state and the
   saved secrets), the nightly backups and the output. Delete or rebuild the app and point it at the
   same folder, and it comes back configured, with no wizard.
2. **Give it to the app's user (uid 568).** In the TrueNAS shell:
   ```sh
   mkdir -p /mnt/pool/printarr
   chown -R 568:568 /mnt/pool/printarr
   ```
   If the folder is not writable, the app stops at once and writes a message to its logs.
3. **Know the printer's IP address** (the Epson TM-T88V on the LAN, port 9100). Have the Home Assistant
   long-lived access token ready too, if you use Home Assistant.
4. **Make sure the image is public** on GitHub (`ghcr.io/ourrage-cmyk/printarr`), so TrueNAS can
   pull it without a login.

## Install

1. In TrueNAS, go to **Apps > Discover Apps > Custom App** (on older releases,
   **Install Custom App**), and choose **Install via YAML**.
2. Paste the whole of [`docker-compose.yml`](../../docker-compose.yml) from the repository.
3. Change the line marked `<- change` if your data folder is different from the default.
4. Save. Wait until the app shows **Running**.
5. Open the app's **Logs**. Find the line that starts `printarr setup: open this printarr's web page`.
   It ends with a **setup code**. Copy it.
6. Open `http://<nas-ip>:30100/` in a browser. The setup wizard opens. Enter the setup code, then fill
   in the printer's IP address, and Home Assistant, the model server and Telegram if you use them.
   Press **Test** on each one. **Finish setup** checks everything again and saves it into the data folder.
   Nothing is saved until every check passes.
7. Check the printer with `curl -X POST http://<nas-ip>:30100/api/v1/printer/test`. It returns 502 if
   the printer is unreachable.

**Secrets never go in the YAML or in environment variables.** The Home Assistant token and the
Telegram bot token are typed into the wizard and stored in the database in the data folder. No
endpoint returns them. Until setup is finished, the API answers 503, except health and the wizard.
The setup code changes at every start. Once setup is finished, the same code opens the wizard at
`http://<nas-ip>:30100/setup`, where you can change any value later, including the printer's IP
address. Each service is checked before anything is saved. A blank token keeps the saved one. Tick
"Remove the saved token" to clear it.

**Moving from the laptop simulator to the real printer:** open `/setup`, enter the code from the
latest log line, change **Printer IP address** to the TM-T88V's address, press **Test**, then **Save
settings**. The printer switches at once, with no restart.

If the timezone changes in the wizard, restart the app once so it takes effect.

The data folder holds everything the app keeps: tickets, the saved settings (printer, decision
model, Home Assistant, Telegram), the database and the backups. Keep it when you upgrade or remove the app.
The database holds the secrets too, so keep the data folder private, and do not share backup files.

## Check that it is healthy

- **Logs:** in TrueNAS, open the app and choose **Logs**. The first lines say which data folder
  and port are in use.
- **Smoke test** from any machine on the LAN, with the repository checked out:
  ```sh
  sh scripts/smoke-test.sh http://<nas-ip>:30100
  ```
  It creates one held ticket (it never prints), reads it back, and checks the backup export.
- **Health for Uptime Kuma:** `http://<nas-ip>:30100/api/v1/health`. It returns 200 when the
  database and printer are fine, and 503 when the printer is unplugged.
- **Build:** `http://<nas-ip>:30100/healthz` returns `version` and `git_sha`. The same build is shown in Settings.
  A local build says `dev`. Check it after each upgrade to confirm the new image is running.
- **Telegram test:** `curl -X POST http://<nas-ip>:30100/api/v1/alerts/test` sends a test message once Telegram is saved.
  Threads ping the owner with `POST /api/v1/notify`, which returns 400 until Telegram is set up.

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
curl -X POST "http://<nas-ip>:30100/api/v1/backup/import?confirm=replace" \
     --data-binary @printarr-backup.db
```

Download a backup from the running app first with `GET /api/v1/backup/export`, or copy a file
from `backups/`. The current database is kept as `backups/pre-import-*.db`, so this can be undone.

**Option B: restore from the data folder** (the app is stopped):

1. Stop the app in TrueNAS.
2. In the TrueNAS shell, replace the database with the copy you want, and remove the journal files:
   ```sh
   cd /mnt/pool/printarr
   rm -f printarr.db-wal printarr.db-shm
   cp backups/<the-copy>.db printarr.db
   chown 568:568 printarr.db
   ```
3. Start the app.

Keep a copy of the current `printarr.db` before step 2 if you may want it back.

## Settings and the printer

- Every setting is saved by the setup wizard in the data folder: the printer, Home Assistant,
  the model server, Telegram, names and timezone. Change them later at `http://<nas-ip>:30100/setup`
  with the setup code from the log. They survive upgrades and rebuilds.
- The YAML holds no settings, so there is nothing to edit there for the printer. To move from the
  simulator to the real printer, change the printer address at `/setup`.

## Nightly backups

- They run at 03:00 local time and keep the last seven copies. These are fixed for now.
- Backups sit on the same SSD as the data. They protect against a bad upgrade or a damaged
  database, not against losing the SSD. Copy the `backups/` folder to another disk now and then.

## Resources and stopping

- The app is limited to 512 MB of memory and one CPU in the YAML. Raise `mem_limit` or `cpus` if
  the logs show it is starved.
- Stopping the app waits up to 30 seconds, so a ticket being printed can finish.

## Troubleshooting

| Symptom in the logs | Cause and fix |
| --- | --- |
| `data folder /data is not writable by uid 568` | Run `chown -R 568:568` on the data folder, then restart. |
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

**Install printarr with the laptop as the printer.** Install the YAML from
[`docker-compose.yml`](../../docker-compose.yml) as it is. In the setup wizard, enter the
laptop's LAN address as the printer's IP address and `9100` as the port, then press **Test** and
**Finish setup**. Then check it, from any machine on the LAN:

```sh
curl http://<nas-ip>:30100/api/v1/printer                  # reachable: true
curl -X POST http://<nas-ip>:30100/api/v1/printer/test      # prints a test receipt
```

The receipt appears in the simulator at `http://localhost:8080` on the laptop. For the full
check, run `sh scripts/smoke-test.sh http://<nas-ip>:30100` as well.

**Switch to the real printer.** Open `http://<nas-ip>:30100/setup` with the setup code from the log, change
**Printer IP address** to the TM-T88V's address, press **Test**, then **Save settings**. The printer switches at once,
with no restart. Tickets, settings and backups stay as they are.
