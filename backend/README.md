# Melnor Timer Backend

Control a Melnor Bluetooth water timer (2-valve unit) from the command line.

## Why this exists

You _can_ drive the timer straight from the terminal (see
[Commands](#commands-not-using-http) below), and that's how the project started.
But the whole point of the app is the **frontend**: a browser UI I can open from
my phone or laptop to check status and start/stop watering without SSHing into
anything. The HTTP API in `api/` exists to back that frontend, the terminal
commands and the API are just two front doors onto the same Bluetooth logic.

> ⚠️ **Run everything from the `backend/` directory.** The `./m` shortcut lives
> here and `cd`'s into its own folder before running, but you invoke it with
> `./m ...`, which only resolves when your shell is _in_ `backend/`. The longer
> `uv run python scripts/control.py ...` form also assumes `backend/` as the
> working directory.
>
> ⚠️ **Close the Melnor phone app first.** Bluetooth allows only one connection
> at a time, if the app is connected, these commands can't reach the timer.

```bash
cd ~/Documents/dev/melnor-test/backend
```

## Commands (not using HTTP)

`./m` is a thin wrapper for `uv run python scripts/control.py`.

| What it does                                            | Shortcut                           | Full command                                                    |
| ------------------------------------------------------- | ---------------------------------- | --------------------------------------------------------------- |
| Show battery, live valve status, **and** schedules      | `./m state`                        | `uv run python scripts/control.py state`                        |
| Show the watering schedule for each zone                | `./m schedule`                     | `uv run python scripts/control.py schedule`                     |
| Turn a zone **ON** for N minutes (manual watering)      | `./m on 1 5`                       | `uv run python scripts/control.py on 1 5`                       |
| Turn a zone **OFF** (stops manual watering only)        | `./m off 1`                        | `uv run python scripts/control.py off 1`                        |
| **Stop** a zone: off **and disable/clear its schedule** | `./m stop 1`                       | `uv run python scripts/control.py stop 1`                       |
| Set a **weekly** schedule (day, 24h time, minutes)      | `./m set-schedule 1 thu 19:00 240` | `uv run python scripts/control.py set-schedule 1 thu 19:00 240` |

Zones are `1` or `2` on the 2-valve timer.

### Notes on each command

- **`on <zone> <minutes>`**: starts watering right now for that many minutes.
- **`off <zone>`**: stops manual watering, but **leaves any schedule enabled**,
  so a scheduled cycle can still run later.
- **`stop <zone>`**: the way to **clear out a schedule**: it turns watering off
  _and_ disables the zone's schedule. Use this when you want a zone to do
  nothing until you set it up again. Example: `./m stop 1` clears zone 1.
- **`set-schedule <zone> <mon-sun> <HH:MM> <minutes>`**: weekly schedule.
  Time is 24-hour (e.g. `19:00` = 7 PM). Examples:
  - `./m set-schedule 1 thu 19:00 240` = zone 1, every Thursday 7 PM, 240 min.
  - `./m set-schedule 1 mon 21:00 20` = zone 1, every Monday 9 PM, 20 min.

  Note this is a **weekly** schedule (repeats every 168 hours on that day). It
  replaces whatever was there, so a previous _daily_ schedule (e.g. every
  24 h at 00:00) becomes once-a-week on the day you set.

## Web API (HTTP)

A FastAPI app in `api/` exposes the same timer controls over HTTP, which is for
running on the Raspberry Pi so a phone/laptop can control the timer over WiFi.

### Start the server

From the `backend/` directory:

```bash
uv run uvicorn api.main:app --reload
```

- `api.main:app` = "in `api/main.py`, use the variable named `app`".
- `--reload` restarts the server automatically when you edit a file (dev only).
- It listens on http://127.0.0.1:8000 by default. To reach it from other devices
  on your network (e.g. the Pi from your phone), add `--host 0.0.0.0` and hit the
  machine's LAN IP, e.g. `http://192.168.1.50:8000`.

Stop it with `Ctrl+C`. Same rules as the CLI apply: **close the Melnor phone app
first** (one Bluetooth connection at a time), and stay in range of the timer.

### Interactive API docs (`/docs`)

Once the server is running, open **http://127.0.0.1:8000/docs** in a browser.
This is FastAPI's built-in **Swagger UI**: every endpoint is listed with its
parameters, and you can call them right from the page ("Try it out" → fill in
`zone`/`minutes` → "Execute") without writing any `curl`. There's also
ReDoc-style docs at **/redoc**.

### Endpoints

**Timer status & control**: these talk to the timer over **Bluetooth** (slow
~15 s per call; one at a time):

| Method | Path                                                        | Does                                              |
| ------ | ----------------------------------------------------------- | ------------------------------------------------- |
| GET    | `/api/state`                                                | Battery, live valve status, and schedules         |
| GET    | `/api/schedule`                                             | The watering schedule for each zone               |
| POST   | `/api/zones/{zone}/on?minutes=N`                            | Water a zone for N minutes (default 5, 1-360)     |
| POST   | `/api/zones/{zone}/off`                                     | Stop manual watering (schedule stays enabled)     |
| POST   | `/api/zones/{zone}/stop`                                    | Watering off **and** disable the onboard schedule |
| POST   | `/api/zones/{zone}/schedule?weekday=D&time=HH:MM&minutes=N` | Set the device's **onboard** weekly schedule      |

`{zone}` is `1` or `2`. Out-of-range values return `422`; if the timer can't be
reached the endpoints return `503`. For `schedule`, `weekday` is `mon`-`sun`,
`time` is 24-hour `HH:MM`, and `minutes` is `1`-`360`. Like the CLI, it sets a
**weekly** schedule (repeats every 168 h) and replaces any existing one.

**Pi-side schedules**: these do **not** touch Bluetooth; they
edit `data/schedules.json` and re-arm the in-process scheduler, so they're
instant and work even when the timer is asleep (no `503`):

| Method | Path                  | Does                                    |
| ------ | --------------------- | --------------------------------------- |
| GET    | `/api/schedules`      | List every saved Pi-side schedule       |
| POST   | `/api/schedules`      | Add a schedule (JSON body, see below)   |
| DELETE | `/api/schedules/{id}` | Delete a schedule by its generated `id` |

**Server:**

| Method | Path              | Does                                               |
| ------ | ----------------- | -------------------------------------------------- |
| GET    | `/api/health`     | Liveness + scheduler status; no Bluetooth (see §7) |
| GET    | `/docs`, `/redoc` | Interactive API docs                               |

#### Two kinds of "schedule"

- **`/api/zones/{zone}/schedule`** sets the timer's own **onboard** schedule,
  limited to a _single_ weekly slot per zone (a device/firmware limit).
- **`/api/schedules`** is the **Pi-side scheduler**: the always-on
  server itself fires manual ON commands on whatever days/times you save, so it
  can do things the device can't (e.g. Mon/Wed/Sat). This is the going-forward
  approach; the onboard schedule is eventually disabled in favour of it.

`POST /api/schedules` takes a JSON body:

```json
{
  "zone": 1,
  "days": ["mon", "wed", "sat"],
  "time": "21:00",
  "minutes": 20,
  "enabled": true
}
```

- `zone` is `1`-`2`; `days` is any of `mon`-`sun`; `time` is 24-hour `HH:MM`
  (local time); `minutes` is `1`-`240` (a scheduled run is capped at 4 hours).
  `enabled` is optional and defaults to `true` (`false` keeps the schedule saved
  but doesn't arm it). Bad values → `422`.
- The response echoes the created schedule including a generated `id`; pass that
  `id` to `DELETE /api/schedules/{id}`.

**Overlap protection.** A new schedule that would clash with an existing one is
rejected with **`409 Conflict`** (the message names the schedule it clashes
with). Two schedules clash when they're on the **same zone**, share a weekday,
and their watering windows (`time` … `time + minutes`) overlap, the check
handles runs that cross midnight or the week boundary. Different zones never
clash, back-to-back runs (one ends as the next begins) are fine, and a
**disabled** (`enabled:false`) schedule is ignored.

Deleting an unknown `id` returns `404`.

```bash
curl http://127.0.0.1:8000/api/schedules            # list

# Add: zone 1, every Mon/Wed/Sat at 21:00, for 20 minutes
curl -X POST http://127.0.0.1:8000/api/schedules \
  -H 'Content-Type: application/json' \
  -d '{"zone":1,"days":["mon","wed","sat"],"time":"21:00","minutes":20}'

curl -X DELETE http://127.0.0.1:8000/api/schedules/a1b2c3d4   # delete by id
```

### `/api/state` response

`watering` is `true` when water is actually flowing, **either** from a manual
`on` command **or** from an active scheduled cycle. While watering, four extra
fields describe it: `watering_source` (`"manual"` or `"scheduled"`), `ends_at`,
`remaining_seconds`, and `remaining_minutes`. They're absent when the zone is
off. The `schedule` block always shows the configured schedule regardless.

```json
{
  "name": "2 Valve Timer",
  "battery": 100,
  "zones": {
    "1": {
      "watering": true,
      "watering_source": "scheduled",
      "ends_at": "2026-07-23T23:00:00",
      "remaining_seconds": 7200,
      "remaining_minutes": 120.0,
      "schedule": {
        "enabled": true,
        "start_time": "19:00:00",
        "interval_hours": 168,
        "duration_minutes": 240,
        "next_run": "Thursday 19:00"
      }
    },
    "2": { "watering": false, "schedule": { "enabled": false } }
  }
}
```

The countdown comes from the device's own end timestamp minus the current time,
so it stays accurate across reconnects (it isn't guessed from when the request
was sent). The CLI's `./m state` shows the same as a
`(scheduled, ~120.0 min left …)` note.

> **Why check both:** the library's `is_watering` flag only tracks _manual_
> watering. A zone running on its _schedule_ shows up in
> `frequency.is_watering` instead, so the state must check both, or a
> scheduled cycle looks "off" while water is flowing.

Examples with `curl`:

```bash
curl http://127.0.0.1:8000/api/state
curl -X POST "http://127.0.0.1:8000/api/zones/1/on?minutes=1"   # zone 1, 1 min
curl -X POST "http://127.0.0.1:8000/api/zones/1/off"            # stop it

# Set a weekly schedule: zone 1, every Monday 21:00, for 20 minutes
curl -X POST "http://127.0.0.1:8000/api/zones/1/schedule?weekday=mon&time=21:00&minutes=20"
```

## Frontend (web UI)

A small **React + Vite + Tailwind** app in `frontend/`. It's a thin client: it
only calls the JSON API above, using **relative** URLs (`/api/...`), so the same
files work no matter the Pi's IP. It needs Node 18+ to _build_, but the Pi never
runs Node to _serve_, FastAPI serves the built static files.

There are two ways to run it:

### Everyday use: build it, FastAPI serves it

```bash
cd frontend
npm install        # first time only
npm run build      # writes frontend/dist
```

`npm run build` produces `frontend/dist`, which `api/main.py` automatically
mounts at `/` (only if that folder exists). So with the backend running, the
whole app is at `http://<pi>:8000/`, one process, one URL. This is what you use
day-to-day. Re-run `npm run build` after any UI change.

### While editing the UI: `npm run dev` (hot reload)

`npm run dev` starts Vite's dev server on port **5173** with live reload, and
proxies `/api` to a backend on the **same laptop** (`localhost:8000`). For
development you run both the backend _and_ Vite locally, never against the Pi:

```bash
# terminal 1, the backend, on your laptop
cd backend
uv run uvicorn api.main:app --reload --port 8000

# terminal 2, the Vite dev server, on your laptop
cd frontend
npm run dev
```

Then open `http://localhost:5173/`. That's the whole dev loop, no Pi, no LAN,
no VPN in the picture. `host: true` is set, so you can also open
`http://<your-laptop-ip>:5173/` from your phone on the same WiFi to check the
mobile layout.

> **Note:** a laptop backend has _no_ Bluetooth link to the timer (the timer
> lives next to the Pi, and it allows only one connection at a time). The
> schedule endpoints are file-based, so add/list/delete work fully offline,
> ideal for UI work. The watering/status buttons just won't reach a real timer
> unless your laptop itself happens to be in Bluetooth range. Test real hardware
> on the Pi build.

`npm run dev` is dev-only. The production build uses plain relative URLs, so it
works no matter what address the Pi is served from.

## Running on a Raspberry Pi (always-on)

Put this on a Raspberry Pi that sits near the timer and stays powered on, so any
phone or laptop on your WiFi can control the valves at `http://<pi>:8000`, no
Mac required. Written for a **Raspberry Pi 4 Model B** running **Raspberry Pi OS
64-bit**. The Pi 4 has built-in Bluetooth, and on 64-bit OS every dependency
installs as a prebuilt wheel (nothing compiles).

> ⚠️ **One Bluetooth connection at a time.** Once the Pi is in charge of the
> timer, stop running the Mac CLI or the phone app against it simultaneously.
> Keep the Pi within Bluetooth range of the timer (~10 m; walls weaken it).

### 1. SSH in and prep the system

```bash
ssh pi@raspberrypi.local          # replace 'pi' with YOUR username
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y git bluetooth bluez
sudo systemctl enable --now bluetooth
```

Set the Pi's timezone to your local zone. **This matters:** the schedule
encoding is based on local time, so a wrong timezone shifts your watering times.

```bash
sudo timedatectl set-timezone America/New_York   # use your zone
```

### 2. Install uv (the Python tool this project uses)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.local/bin/env         # or open a new SSH session so `uv` is on PATH
uv --version                    # confirm it's installed
```

### 3. Get the code onto the Pi

Clone it from GitHub:

```bash
git clone https://github.com/ubemacapuno/melnor-pi-bridge.git ~/melnor-test
```

git is the deploy method here: `git pull` gives reproducible updates from a
known commit (see [Updating the code later](#updating-the-code-later)). It never
touches the gitignored `backend/data/` (your live `schedules.json`), the `.venv`,
or the frontend build dirs, all of which are created on the Pi in step 4.

### 4. Install dependencies and build the web UI on the Pi

```bash
cd ~/melnor-test/backend
uv sync                 # builds a fresh Linux .venv from uv.lock
```

The frontend is a React app that FastAPI serves as static files, so it must be
**built on the Pi**. It needs Node 18+, check with `node -v`. If it's missing,
install a current version:

```bash
curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
sudo apt install -y nodejs
```

Then build it (only Node is needed for the build; the Pi never runs Node to
_serve_ the app, FastAPI does):

```bash
cd ~/melnor-test/frontend
npm install             # first time only; pulls React/Vite/Tailwind
npm run build           # writes frontend/dist, which FastAPI serves at /
```

### 5. Confirm Bluetooth works

With the timer awake and the phone app closed:

```bash
./m state
```

Battery + valve status means the Pi can talk to the timer. _(If scanning fails
with a permission error: `sudo usermod -aG bluetooth $USER`, then log out/in.)_

### 6. Run the server for your whole network

```bash
uv run uvicorn api.main:app --host 0.0.0.0 --port 8000
```

`--host 0.0.0.0` makes it reachable from other devices (not just the Pi itself);
we drop `--reload` (that's dev-only). Find the Pi's IP with `hostname -I`, then
from any device on your WiFi open:

- `http://<pi-ip>:8000/`: the **web UI** (built in step 4). If you skipped the
  frontend build you'll get a 404 here; the API below still works.
- `http://<pi-ip>:8000/docs`: the interactive API docs.

### 7. Start on boot and stay running (systemd)

`Ctrl+C` kills the command above. A **systemd service** keeps the API running
24/7 and restarts it after a crash or reboot, this is the real "install."

```bash
sudo nano /etc/systemd/system/melnor.service
```

Paste this, replacing `pi` with your username in **all three** places:

```ini
[Unit]
Description=Melnor Timer API
After=bluetooth.target network-online.target
Wants=network-online.target

[Service]
User=pi
WorkingDirectory=/home/pi/melnor-test/backend
ExecStart=/home/pi/melnor-test/backend/.venv/bin/uvicorn api.main:app --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

`Restart=on-failure` restarts the API if it crashes (a clean `systemctl stop`
won't trigger a restart); `enable` + `WantedBy=multi-user.target` starts it on
every boot. That's the "start up and restart on fail" behaviour you want.

Enable and start it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now melnor
sudo systemctl status melnor      # should say 'active (running)'
journalctl -u melnor -f           # live logs (Ctrl+C to stop watching)
```

The API now comes up at `http://<pi>:8000` after every reboot.

**Because the scheduler runs INSIDE this process, three things
matter for the service:**

- **Run exactly ONE process.** Do NOT add `--workers 2` (or run it under
  gunicorn with multiple workers). Each worker starts its own copy of the
  scheduler, so every watering schedule would fire two-plus times at once and
  the firings would fight over the single Bluetooth connection. One uvicorn
  process is correct here.
- **Set the Pi's timezone.** Schedules are stored in _local_ time, and the
  scheduler uses the system timezone. Set it once so 21:00 means 21:00:
  ```bash
  sudo timedatectl set-timezone America/Phoenix   # use your own zone
  ```
- **Restart re-arms schedules automatically; it does NOT catch up missed
  runs.** On startup the app reads `data/schedules.json` and re-arms every
  alarm, so the schedule _list_ survives crashes and reboots. But a run whose
  time passed _while the service was down_ is skipped, not run late (a known
  gap we may close later with run-history + catch-up). `data/schedules.json` is
  the source of truth and lives under `backend/data/`, so it persists across
  restarts and code updates, don't delete it.

You can watch a schedule fire in the live logs (`journalctl -u melnor -f`):
look for lines like `Schedule <id> firing: zone 1 for 20 min`.

**Health check.** `GET /api/health` is an instant liveness check that does NOT
touch Bluetooth (so it won't fail just because the timer is asleep):

```bash
curl http://<pi>:8000/api/health
# {"status":"ok","scheduler":{"running":true,"jobs":2}}
```

`jobs` is how many alarms are armed, compare it to your count of _enabled_
schedules from `GET /api/schedules` to confirm they all armed after a reboot.
Note `Restart=on-failure` only restarts a process that has _exited_; to catch a
process that's alive but wedged, point an external uptime check at this URL.

### 8. Stable address & remote access

- **Stable address:** give the Pi a DHCP reservation (or static IP) in your
  router so its address doesn't change, or just use `http://<hostname>.local:8000`.
- **Do NOT port-forward 8000 to the internet**: it would let anyone open your
  valves with no password. For control away from home, install **Tailscale** on
  the Pi and your phone (free, encrypted, no open ports).

### Updating the code later

With git cloned on the Pi (step 3) and the app under systemd (step 7), an update
is a few commands **on the Pi**:

```bash
cd ~/melnor-test
git pull                                 # fetch the latest from GitHub
cd frontend && npm run build && cd ..    # only if the UI changed
sudo systemctl restart melnor            # pick up the new code
```

Notes:

- **Push from your Mac first** (`git push`). The Pi's `git pull` only sees what's
  already on GitHub, not your Mac's uncommitted edits.
- `git pull` never touches `backend/data/` (gitignored), so the Pi's live
  `schedules.json` is safe across every update.
- The `npm run build` step is only needed when the **frontend** changed; `dist/`
  isn't in git, so the Pi rebuilds it from source. Skip it for backend-only
  changes.
- Run `uv sync` in `backend/` too if the **Python dependencies** changed.
- Watch it come back up with `journalctl -u melnor -f`, then hard-refresh
  `http://<pi>:8000/`.

> In production there is ONE process: the backend serves the built frontend, so
> a UI change just means rebuild `dist` and restart the backend. A UI-only
> change technically serves fresh from disk without a restart, but restarting is
> harmless and removes doubt.
