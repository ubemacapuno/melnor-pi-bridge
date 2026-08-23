# Melnor Pi Bridge

A self-hosted controller for a **Melnor Bluetooth water timer** (2-valve unit).
It turns a Raspberry Pi sitting near the timer into a BLE→WiFi (Bluetooth Low Energy) bridge. The
Pi talks to the timer over Bluetooth, and I get a browser UI I can open from my
personal device (over a [Tailscale](https://tailscale.com/) network) to check status and start/stop watering.

## Why I built this

I have two trees in my yard that I keep alive with garden hoses, and I already
had the Melnor timer to run them. The problem was controlling it. The Melnor
was talking over **Bluetooth**, through its phone app, so I had to be within
close range of the unit to connect. Even then the Bluetooth was weak and
would occasionally drop connection.

I addressed the problem by placing a Raspberry Pi near the timer to
hold the Bluetooth connection full-time. The Pi then exposes control over my
home WiFi and Tailscale, so I can water on a schedule or start/stop on demand
from anywhere, without fighting a flaky Bluetooth connection by the spigot.

The two trees in question, and the Melnor timer wired up to the spigot:

<img src="https://res.cloudinary.com/dntiqucwf/image/upload/f_auto,q_auto,w_600,c_limit/v1787445645/melnor/IMG_8680_ydxpc1.webp" width="300" alt="One of the two trees watered by the Melnor timer">
<img src="https://res.cloudinary.com/dntiqucwf/image/upload/f_auto,q_auto,w_600,c_limit/v1787445644/melnor/IMG_8688_h3zufr.webp" width="300" alt="The second tree watered by the Melnor timer">
<img src="https://res.cloudinary.com/dntiqucwf/image/upload/f_auto,q_auto,w_600,c_limit/v1787445642/melnor/IMG_8681_reju37.webp" width="300" alt="The Melnor Bluetooth water timer mounted on the outdoor spigot">

## What it does

- **Manual watering**: turn either zone on for x minutes, or off, from a browser.
- **Scheduling**: set weekly watering schedules. A small in-process scheduler on
  the Pi fires them even when the timer is asleep, so the schedule lives on the
  Pi rather than depending on the timer's flaky onboard scheduler.
- **Status at a glance**: battery level, live valve state, and upcoming schedules.

The browser UI:

<img src="https://res.cloudinary.com/dntiqucwf/image/upload/f_auto,q_auto,w_800,c_limit/v1787446885/melnor/Screenshot_2026-08-22_at_6.00.12_PM_gvs1dw.webp" width="400" alt="The Melnor Pi Bridge browser UI showing valve status and controls">

## Tech stack

| Layer             | Tech                                                                                                                  |
| ----------------- | --------------------------------------------------------------------------------------------------------------------- |
| **Frontend**      | React 18 + TypeScript, Vite, Tailwind CSS v4                                                                          |
| **Backend**       | FastAPI (Python 3.11), managed with `uv`                                                                              |
| **Bluetooth**     | [melnor-bluetooth](https://github.com/vanstinator/melnor-bluetooth) (talks BLE to the timer via the Pi's BlueZ stack) |
| **Host**          | Raspberry Pi, kept alive by a `systemd`                                                                               |
| **Remote access** | Tailscale, a private VPN (tailnet) so I can reach the Pi from anywhere, not just my home WiFi                         |

FastAPI serves the built React app as static files, so the whole thing runs as a single process on one port.

## Flow Overview

```
Phone / laptop
      |  HTTPS over Tailscale (or plain HTTP on the home LAN if the server is
      |  bound to 0.0.0.0 instead of loopback; mine is Tailscale-network-only!)
      v
Raspberry Pi  ==>  FastAPI (serves the React UI + the HTTP API)
      |
      |  Bluetooth
      v
Melnor 2-valve water timer
```

Tailscale is what lets me control the timer while away from home. My devices and
the Pi all join the same private tailnet, and I hit the Pi over that encrypted
tunnel instead of exposing anything to the public internet.

## File layout

```
backend/    FastAPI app, BLE control logic, scheduler, and CLI tools
frontend/   React + TypeScript UI (Vite)
```

## Getting started

The backend is where most of the setup lives: running the server, the CLI, the
Bluetooth quirks, and deploying to the Pi. See **[`backend/README.md`](backend/README.md)**.

Quick version:

```bash
# Backend
cd backend
uv run uvicorn api.main:app --reload      # http://127.0.0.1:8000

# Frontend
cd frontend
npm install
npm run dev                                # Vite dev server
npm run build                              # production build FastAPI serves
```
