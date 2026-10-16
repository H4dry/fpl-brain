# FPL Brain — v0.2

A responsive, beginner-friendly FPL analytics prototype. It now includes a small local Python server that serves the UI, proxies read-only FPL public data with a cache, and offers an optional server-side AI endpoint compatible with OpenAI-style chat-completions APIs.

## What is implemented

- Responsive single-page web UI.
- Read-only FPL bootstrap data proxy at `/api/fpl/bootstrap` with a 10-minute default cache.
- Fixture proxy at `/api/fpl/fixtures`.
- Health/status endpoint at `/api/health`.
- Live player browser with search, position filter, club, current FPL price, points, minutes, goals, assists, clean sheets, selected-by percentage, and availability fields where supplied by FPL.
- Player comparison using actual fields from the official public FPL feed when successfully connected. It does **not** invent xG/xA or expected points.
- Optional server-side AI chat at `/api/ai/chat`. The browser never receives the API key.
- Transfer budget arithmetic, saved transfer ideas, timestamped prediction log, scoring, MAE and CSV export using this browser's local storage.
- Clear fallback messages if live data or AI cannot be reached.

## What is not implemented / not verified

- No live endpoint request could be tested in the build environment because outbound DNS/network access was unavailable. The app must be run on a device with internet access and the Connect button tested.
- FPL's public API is undocumented and can change; use is not guaranteed. Review the current Premier League terms before public deployment.
- Advanced xG/xA, event data, and true player-tracking heatmaps are **not** provided by the FPL bootstrap feed. The current heatmap remains a labelled placeholder until a permitted source is configured.
- No automatic expected-points model, legal full-squad solver, injury-news aggregator, account login, cloud database, or multi-device sync yet.
- Prediction records remain in browser local storage; export CSV backups regularly.
- AI provider integration is optional and was not tested against a real provider. An API key and billable account may be required depending on the provider.

## Run on Windows

1. Install Python 3.10 or newer from https://www.python.org/downloads/ (enable “Add Python to PATH”).
2. Extract the ZIP folder.
3. Double-click `run.bat`.
4. Open http://127.0.0.1:8000 in Chrome or Edge.
5. Click **Connect live data**. If the connection fails, the interface reports the failure rather than displaying live status.

## Run on macOS / Linux

From this folder, run:

```sh
python3 server.py
```

Then open http://127.0.0.1:8000.

## Optional AI setup

Copy `.env.example` as a reference only. The server does not automatically load `.env` files. Set these environment variables in the terminal/session that starts the server:

- `FPL_AI_BASE_URL` (default `https://api.openai.com/v1`)
- `FPL_AI_API_KEY`
- `FPL_AI_MODEL`

Restart the server after setting them. Do not put real keys into `index.html`, upload them to GitHub, or share them in chat. The endpoint expects an OpenAI-style `/chat/completions` interface; other provider formats may require an adapter.

PowerShell example (replace placeholders locally; do not share the key):

```powershell
$env:FPL_AI_API_KEY = "YOUR_KEY"
$env:FPL_AI_MODEL = "YOUR_MODEL"
$env:FPL_AI_BASE_URL = "https://api.openai.com/v1"
py -3 server.py
```

## Architecture

- `index.html`: responsive UI and client-side interactions.
- `server.py`: local HTTP server, read-only FPL proxy, basic cache/schema checks, optional AI relay.
- `.env.example`: configuration template only; no secret is included.
- `run.bat` / `run.sh`: launch scripts.

## Data-source notes

- Official FPL site: https://fantasy.premierleague.com/
- Public endpoint examples (undocumented): `https://fantasy.premierleague.com/api/bootstrap-static/` and `/api/fixtures/`
- Community notes on endpoints: https://github.com/jakesmith1997-sfc/fpl-api
- StatsBomb Open Data (selected competitions/seasons only; attribution and terms apply): https://github.com/hudl/open-data

FPL Brain is an independent project and is not affiliated with or endorsed by the Premier League.
