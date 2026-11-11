# Hamstra — From-Scratch Build Plan (original plan; the app was called "Arr" while it was built)

Goal: one platform that replaces Sonarr, Radarr, Prowlarr and the torrent client (qBittorrent), with one GUI and one process/container. Plex stays as the existing container and is only notified and read from.

## Architecture

```
            ┌────────────── Web UI (React/Svelte) ──────────────┐
            │ dashboard · library · search · queue · calendar    │
            └───────────────┬─────────── REST + WebSocket ───────┘
                            │
 ┌──────────────────────────▼───────────────────────────────────┐
 │ Core API (Go or Python/FastAPI)                               │
 │  metadata · library · parser · indexers · decision · queue    │
 │  importer · scheduler · notifications · auth                  │
 └──────┬──────────────┬─────────────┬──────────────┬───────────┘
        │              │             │              │
     SQLite/PG     TMDB/TVDB     Built-in indexer   Built-in torrent engine
                                 manager (Prowlarr  (python libtorrent,
                                 replacement)       own worker thread)
                                                       │
                          shared /data volume ──► Plex container (scan trigger)
```

Decisions to make in M0:
- Language: Python 3.12. Flask is fine for the REST API. Realtime (queue progress) uses Server-Sent Events or Flask-SocketIO. Background jobs use APScheduler plus worker threads in-process. Run under gunicorn with a single worker (or gevent) so the libtorrent session is owned by one process.
- Flask vs FastAPI: FastAPI gives async, websockets, and auto-generated OpenAPI docs for free. Flask works but needs add-ons for those. Keeping the core in plain service modules, with a thin HTTP layer on top, makes the framework easy to swap.
- Torrent engine: built in, using libtorrent (`python-libtorrent` / `libtorrent` wheel). It runs as a long-lived session in its own thread, behind an `Engine` interface. A qBittorrent adapter stays as an optional fallback and for dev.
- Indexers: built-in indexer manager (Prowlarr replacement) with Torznab, RSS and Cardigann-style YAML definitions, so community tracker definitions can be reused.
- DB: SQLite at first, with migrations.
- Auth: local user plus API key, behind a reverse proxy.

## Milestones

| # | Milestone | Deliverables | Est. (solo) |
|---|---|---|---|
| M0 | Foundations | Repo, compose file for the app, DB schema and migrations, config, auth, CI, API skeleton | 3–5 d |
| M1 | Metadata | TMDB client (movies and TV), cache, posters, series/season/episode model, search endpoint | 1 wk |
| M2 | Library core | Add/monitor movies and series, root folders, quality profiles, library table, existing-file scan and matching | 2 wk |
| M3 | Release parser | Parse title, year, SxxExx, season packs, daily and anime numbering, resolution, source, codec, group, proper/repack. Test corpus of 1000+ real names | 2 wk |
| M4 | Indexer manager (Prowlarr replacement) | Torznab and RSS clients, YAML definition engine (Cardigann-compatible subset), indexer CRUD and test, capability caps, rate limiting, per-indexer health, unified search across indexers, proxy/FlareSolverr support | 3 wk |
| M5 | Decision engine | Quality ranking, cutoffs, size limits, custom formats and scores, upgrade logic, blocklist, seeders and age rules | 2 wk |
| M6 | Built-in torrent client | libtorrent session manager, add by magnet/.torrent, queue, pause/resume, limits, seeding ratio/time rules, categories, resume data, VPN-bind/interface binding, port forwarding, progress over SSE/WebSocket, optional qBittorrent adapter | 3 wk |
| M7 | Importer | Completed-download detection, hardlink/move/copy, rename templates, season-pack handling, cleanup, Plex library scan trigger | 2 wk |
| M8 | Automation | Scheduler for RSS sync, missing and cutoff-unmet searches, new-episode monitoring, calendar feed | 1 wk |
| M9 | Unified GUI | Dashboard, library grid, detail pages, manual search with release list, queue, history, calendar, settings, activity log | 3–4 wk (parallel from M2) |
| M10 | Plex and notifications | Plex token and library mapping, scan on import, watched-state read, Discord/webhook/email notifications | 1 wk |
| M11 | Hardening | Backups, import/export, logging, metrics, security review, load test, docs, Docker image | 1–2 wk |
| M12 | Optional | Own libtorrent engine, requests/users, subtitles, lists (Trakt/IMDb), anime (AniDB), music/books | later |

Total to an MVP (M0–M9): about 18–22 weeks solo (the built-in indexer manager and torrent client add about 4 weeks). M12 is open-ended.

## MVP cut line (usable in about 8–10 weeks)
Movies and TV, TMDB metadata, Torznab/RSS indexers, built-in libtorrent client (qBittorrent adapter as a stopgap while M6 is built), quality profiles without custom formats, hardlink import, Plex scan, basic UI. Defer custom formats, anime, lists and requests.

## Hardest parts (budget extra time)
1. **Release parser.** Build the test corpus first and treat it as test-driven development.
2. **Importer.** Files need atomic moves, hardlinks across mounts, and partial or multi-episode files. The compose volume layout must put downloads and media on the same filesystem.
3. **Upgrade and decision logic.** Wrong behaviour here means re-downloading or replacing good files.
4. **Indexer quirks.** Bad XML, odd categories, rate limits, Cloudflare. Cardigann definitions reduce this but need an interpreter.
5. **Embedded torrent engine.** Resume data, long-running session stability, and VPN leak prevention (bind to the VPN interface or run the container inside the VPN network namespace). A crash takes down the API unless the engine runs as a separate process or worker, which is the safer design.

## Data model (core tables)
`movies`, `series`, `seasons`, `episodes`, `episode_files`, `quality_profiles`, `custom_formats`, `indexers`, `download_clients`, `queue_items`, `history`, `blocklist`, `root_folders`, `settings`, `users`, `tasks`.

## Testing strategy
- Parser: table-driven tests from a real-name corpus.
- Decision engine: golden scenarios (upgrade, cutoff met, size reject).
- Importer: temp-directory filesystem tests, including hardlink and cross-device cases.
- Integration: a docker-compose test stack with a fake indexer and a real qBittorrent.
- Dry-run mode that logs decisions without downloading.

## Compose integration
- Add the app as one service beside the existing Plex container. It replaces the Sonarr, Radarr, Prowlarr and qBittorrent containers. Route it through the VPN container with `network_mode: service:gluetun` if you use one.
- Mount the same `/data` root in all containers, with `/data/torrents` and `/data/media/{movies,tv}`.
- Match PUID/PGID to Plex's.
- Route the torrent client through a VPN container if desired.

## Risks
- Scope creep. Hold the MVP line.
- Indexer maintenance. Support Torznab and RSS first, then YAML definitions.
- Legal. Use only for content you have rights to.
- Metadata API limits and terms. Cache aggressively.

## Immediate next steps
1. Decide language and engine approach (M0).
2. Share your existing compose file, so the volume layout and Plex setup can be matched.
3. Start the parser test corpus now.
4. Scaffold the repo and the API skeleton.
