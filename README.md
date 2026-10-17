# FPL Brain — v0.4

A responsive FPL analytics app with a read-only FPL data proxy, a persistent SQLite snapshot pipeline, historical player trends, and an optional advanced-stat provider adapter. It does not fabricate missing xG/xA or event data.

## What's implemented

- Responsive single-page UI with Dashboard, AI Chat, Squad & Transfers, Team Builder, Prediction Lab, Analytics, Stats & Heatmaps, and Data Sources.
- `/api/fpl/bootstrap` and `/api/fpl/fixtures`: cached official public FPL endpoints with schema checks and persistent stale-snapshot fallback if the upstream is unavailable.
- `/api/data/status`: per-feed freshness, source, and snapshot status for bootstrap, fixtures, and optional advanced stats.
- SQLite storage (`fpl_brain.sqlite3`) for changed snapshots and selected player fields; duplicate payloads are not stored, and the latest 180 changed snapshots per feed are retained.
- `/api/fpl/history?player_id=123&limit=30`: time series for a player's saved price, minutes, points, form, selected-by percentage, and any xG/ICT fields present in the FPL feed.
- `/api/fpl/advanced-stats`: optional HTTPS JSON adapter for a third-party stats source. Last successful advanced-stat payload is saved and used as a clearly labelled stale fallback if the provider fails.
- Analytics Pro: underlying stats ranking, filters, FPL fixture outlook (including multiple fixtures in a GW), player comparisons, data freshness panel, and historical trend chart from snapshots.
- Missing stats remain `—`; provider values are merged only when a player can be matched by official FPL ID or unique player name/team.
- Optional server-side AI chat endpoint at `/api/ai/chat`; browser never receives the API key.

## Important limitations

- The official FPL API is undocumented and can change. Check current terms and respect rate limits before public deployment.
- **xG/xA, shots, big chances, key passes, defensive contribution fields and event coordinates are not guaranteed by the FPL bootstrap.** Analytics can show these only when the FPL feed actually includes them or a permitted provider is configured.
- This app does not bundle an external paid-data key or scrape a provider. You must select a source whose licence/terms allow your intended use, then set `FPL_ADVANCED_STATS_URL` and optionally `FPL_ADVANCED_STATS_TOKEN`.
- Historical trends begin when the v0.4 server first saves changed snapshots. Old data cannot be reconstructed retroactively. For long-term charts, the server's SQLite file must persist across restarts/deploys.
- A fresh snapshot means a successful response from that source, not a guarantee that the source's underlying data is complete or correct.
- Prediction Lab includes a transparent heuristic forecast and an independent historical rolling-baseline backtest. It is not a trained or fully validated predictive model; compare its results against the baseline and official FPL `ep_next`.

## Advanced stats provider response contract

Set `FPL_ADVANCED_STATS_URL` to a permitted HTTPS endpoint returning either an array of player objects or an object containing a `players` array. Example:

```json
{
  "players": [
    {
      "fpl_id": 123,
      "web_name": "Player Name",
      "team_name": "Example FC",
      "expected_goals": 1.23,
      "expected_assists": 0.45,
      "expected_goal_involvements": 1.68,
      "expected_goals_conceded": 2.10,
      "shots": 12,
      "shots_on_target": 5,
      "big_chances": 3,
      "big_chances_created": 2,
      "key_passes": 8,
      "defensive_contribution": 14
    }
  ]
}
```

`fpl_id` must be the official FPL element ID. If you don't have it, supply an exact `web_name` and `team_name`; name-only matching is used only when the name uniquely identifies one player. Only whitelisted fields are passed to the browser. If the provider needs a bearer token, set `FPL_ADVANCED_STATS_TOKEN` on the server. Never put credentials in HTML or commit real tokens to GitHub.

## Run locally

Python 3.10+; no third-party Python packages required.

```bash
python server.py
```

Open `http://127.0.0.1:8000` and click **Connect live data**. On Windows, `run.bat` is also provided.

## Deploy notes

The app's SQLite database is local to the server by default. Use a persistent disk/path if your host resets files on deploy.

### PythonAnywhere (WSGI)

This bundle includes `wsgi_app.py`. In the PythonAnywhere WSGI configuration file, set the project directory on `sys.path`, then import `application` from `wsgi_app` (the project folder must contain `index.html`, `server.py`, and `wsgi_app.py`). Reload the web app after uploading all three files. Example:

```python
import sys
project_home = '/home/YOUR_USERNAME/fpl-brain'
if project_home not in sys.path:
    sys.path.insert(0, project_home)
from wsgi_app import application
```

Ensure the project directory is writable so SQLite can create `fpl_brain.sqlite3`, or set `FPL_DB_PATH` to a writable persistent path. The new API routes must be deployed with the HTML; uploading `index.html` alone will not activate the data pipeline. Set optional provider environment variables in the host's environment, never in the HTML.

### Standalone server

Run `python server.py`; it serves the same API routes and static UI on the configured port.

FPL Brain is an independent project and is not affiliated with or endorsed by the Premier League.


## v0.5 Prediction Engine & Transfer Optimizer
- Prediction Lab estimates next-GW points and participation chance using FPL season points, form, minutes, availability fields and fixture difficulty. Official FPL `ep_next` is displayed separately.
- Historical walk-forward backtest predicts each gameweek from the previous three gameweeks, including zero-minute rounds, and reports MAE, bias, zero-minute error and gameweek-level errors. It tests a rolling baseline, not the live heuristic.
- Transfer optimizer searches legal replacements for a saved 15-player Team Builder squad, enforces position and club limits, applies the bank and transfer hits, and evaluates the best starting XI across the chosen horizon. It separately recommends next-GW XI, captain and vice-captain.
- The model is a transparent heuristic, not trained/validated ML. Actual selling prices must be checked manually; the optimizer uses current listed prices as a proxy.
