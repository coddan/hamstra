# 🐹 Hamstra — movies, series, music and downloads in one place

Hamstra (Swedish for *to hoard*) is one self-hosted app that replaces Radarr, Sonarr, Prowlarr, Lidarr and a torrent client, with a single web UI.
It finds releases on your trackers, downloads them with a built-in torrent client, copies them into your library with
proper names, keeps seeding until your ratio/time rule is met, then cleans up. Plex is told which folder changed.

## What it does
- **Movies and series** (TMDB / TVmaze metadata), kids/adults routing for movies, season packs, daily shows, upgrades, quality profiles.
- **Music** (MusicBrainz): add an album, pick a release, choose the genre folder; existing albums are recognised and can be linked in bulk.
- **Others**: search every tracker for anything (apps, games, books), upload `.torrent` files or magnet links. Downloaded as-is, never renamed.
- **Indexers**: IPTorrents (cookie), HDBits (username + passkey), Torznab/RSS (Jackett, Prowlarr), archive.org (free).
- **Interactive search** everywhere, with the reason every rejected release was rejected.
- **Library tools**: automatic matching of existing folders, a review page for the rest, best-guess matching you can undo, per-folder types (movies / series / mixed / music).
- **Safety**: dry-run automation, VPN kill switch, free-space check, stalled-download handling, verified copies, nightly backups with one-click restore.
- Optional: subtitles (OpenSubtitles account needed), Trakt/TMDB list import, requests for extra users, webhook notifications.

## Install (Docker or Podman)
1. `cp docker-compose.example.yml docker-compose.yml` and edit the values marked CHANGE (mainly your TMDB token and folder paths).
2. `docker compose up -d --build`, then open `http://<host>:8000`.
3. **Create the admin account at once.** Until the first account exists the app is open to everyone on your network.
4. Settings → Library → Media folders: check that each folder has the right type.
5. Settings → Indexers → add your trackers. Settings → Plex & notifications → add Plex (see below).

With Podman, build with `--format docker` so the health check is kept. Keep the downloads folder and your library on the same share. On network shares (SMB) hardlinks are impossible, so imports are
size-verified copies: files exist twice until seeding finishes and the download copy is removed.

## Plex
Use the LAN address, not plex.tv: `http://<plex-host>:32400`, plus an X-Plex-Token (Plex Web → any item → ⋯ → Get info → View XML,
the link ends in `X-Plex-Token=...`). After each import only the changed folder is scanned. Plex libraries must point at the same folders.

## Safe start with automation
Settings → Downloads & seeding → Automatic downloading: leave **Dry run** ticked and switch it on. For a day the app only records what it
*would* download (shown as "would grab" in the Queue history). Check it, then untick Dry run.

## HTTPS and reverse proxy
Put the app behind a reverse proxy (Caddy, nginx, Traefik) for HTTPS and set `HAMSTRA_SECURE_COOKIES=true`. Example Caddyfile:

    hamstra.example.com {
        reverse_proxy hamstra:8000
    }

The container already trusts `X-Forwarded-For`, so login rate limits see the real client address.

## VPN
Either run the app through a VPN container (see the gluetun block in the compose file) or bind the torrent client to a VPN interface
(Settings → Downloads & seeding). With a VPN interface set, nothing is grabbed and active torrents pause while it is down.

## Backups and restore
The database is copied every night at 03:30 (last 14 kept) into `<config>/backups`. System → Backups: download, back up now, or
**Restore…** (the current database is kept as a backup first; the swap happens on the next start, there is a Restart button).

## Not covered
- Cloudflare-protected trackers: IPTorrents cookies are tied to your IP and expire; when that happens the Indexers page shows the error.
- Anime absolute numbering, TV specials (season 0), retagging music files (your files are never modified).
- Subtitle and Trakt support are written against their public APIs but need your own keys; they were tested with mocked servers only.

## Development
    cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/pytest
    cd frontend && npm install && npm run dev        # proxies /api to :8000
    ./e2e/README.md                                   # browser check with screenshots (Playwright, in a container)

Settings come from `HAMSTRA_*` environment variables (the older `ARR_*` names still work; see `backend/app/config.py`) and from the Settings pages.
Database migrations (Alembic) run automatically at start.

## Kubernetes

A Helm chart is in [`deploy/helm/hamstra`](deploy/helm/hamstra) (see its README). It is linted and renders correctly, but has not been tried on a real cluster.
