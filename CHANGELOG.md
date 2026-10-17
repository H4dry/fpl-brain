# Changelog

## v0.3 — Data pipeline + Analytics Pro
- Added persistent SQLite snapshots for FPL bootstrap, fixtures, and optional advanced-stat payloads.
- Added stale-snapshot fallback with explicit freshness/stale metadata.
- Added `/api/data/status`, `/api/fpl/history`, and `/api/fpl/advanced-stats`.
- Added configurable HTTPS advanced-stat provider adapter and field whitelist.
- Added Analytics data-pipeline monitor and player history chart.
- Added provider merge by FPL ID or grounded name/team match; missing fields stay blank.
- Retained clear separation between official FPL feed data and third-party data.


## v0.4 — Engine & Transfer Optimizer
- Added a transparent heuristic for one-gameweek expected points and participation probability. Official FPL ep_next remains a separate comparison column.
- Added walk-forward historical appearance backtest using each player's prior three appearances as a baseline; reports MAE and bias.
- Added transfer search against a saved 15-player Team Builder squad, with FPL squad/club limits, bank, free transfers and -4 hits.
- Added a cached read-only proxy for FPL element-summary history.
- Forecasts are heuristic and not a trained/validated predictive model.


## v0.5 — Prediction Engine + Transfer Optimizer improvements
- Improved the Prediction Lab table labels and made the model's points-if-playing and availability assumptions explicit. Official `ep_next` remains separate.
- Historical walk-forward backtest now includes zero-minute gameweeks instead of filtering them out, and reports overall MAE, bias, zero-minute cases, and gameweek-level MAE.
- Transfer optimizer now compares best legal starting XIs across the selected horizon rather than summing all 15 squad players as if they all scored.
- Optimizer ranks candidate moves after hit costs and shows a separate next-GW best XI, captain and vice-captain.
- Fixture model now treats a confirmed blank gameweek as zero fixture contribution when the schedule for that event is available.
- Search remains bounded and current market prices are still proxies for actual FPL selling prices; recommendations are heuristic, not guarantees.
