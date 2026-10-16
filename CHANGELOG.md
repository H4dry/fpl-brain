# Changelog

## v0.2 — 2026-10-16

- Added local Python server with `/api/health`, `/api/fpl/bootstrap`, `/api/fpl/fixtures`, and optional `/api/ai/chat`.
- Added read-only public FPL proxy with a 10-minute in-memory cache and response-shape checks.
- Added live connection button and honest connection status/failure messages.
- Added current player search/filter, FPL stats fields, current prices, and next-fixture lookup when available.
- Added player dropdowns to prefill outgoing/incoming market prices in transfer calculator; actual selling price must still be verified by the manager.
- Added optional server-side AI configuration via environment variables; no API key in frontend files.
- Kept xG/xA and tracking heatmaps explicitly marked as not connected.
- Fixed and checked JavaScript syntax; smoke-tested local HTTP routes. External FPL request failed in the build environment because DNS/network access was unavailable, so live connectivity remains unverified.
