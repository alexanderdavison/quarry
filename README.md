# Quarry — Mine videos. Preserve knowledge.

Scrapes YouTube videos into permanent, searchable Obsidian notes (metadata + full timestamped transcript) and seeds Honcho memory per topic bucket.

## Architecture

| Component | Location |
|-----------|----------|
| LXC | 101 `quarry` on pve-m910-01 (192.168.1.13) |
| WebUI | http://192.168.1.21:5000 (`quarryd.service`, Flask, port 5000) |
| App dir | `/opt/quarry/` — `webui.py`, `index.html`, `quarry` (scraper CLI, no extension) |
| Venv | `/opt/scraper-venv/` (yt-dlp + youtube-transcript-api + Flask) |
| Vault | `/mnt/obsidian-vault` (NFS bind via host; `{category}/youtube/*.md`) |
| Honcho | http://192.168.1.23:8000 (workspaces per category, see below) |

## Categories → vault path → Honcho workspace

| Category | Vault dir | Honcho workspace |
|----------|-----------|------------------|
| sources | `sources/youtube/` | `hermes` |
| shared | `shared/youtube/` | `hermes` |
| homelab-wiki | `homelab-wiki/youtube/` | `hermes` |
| personal-wiki | `personal-wiki/youtube/` | `hermes` |
| ish-d | `ish-d/youtube/` | `hermes_ish-d` |
| real-estate | `real-estate/youtube/` | `hermes_real-estate` |
| dental-msp | `dental-msp/youtube/` | `hermes_dental-msp` |
| axiom-music | `axiom-music/youtube/` | `hermes_axiom-music` |

Vault docs are seeded into per-profile Honcho workspaces by `seed-vault-to-honcho.sh` (Hermes cron `vault-honcho-seed`, 06:00 UTC).

## UI flow

Home page: paste YouTube link → pick bucket ("Save to:" pills) → **Transcribe & Save** → note lands in `{bucket}/youtube/` with a View-note link. Import page mirrors the form. Vault page lists buckets + notes. Memory page shows Honcho health + per-note sync status with retry.

## API

- `POST /scrape` `{url, category}` → runs scraper, writes vault note, seeds Honcho
- `GET /recent` → `{scrapes: [...]}` (id, title, channel, category, path, summary, timestamp, honcho_sync_status)
- `GET /api/vault` → bucket cards with file counts (sorted mtime desc)
- `GET /view/<vault-rel-path>` → raw markdown note
- `POST /delete-scrape` `{id}`; `POST /api/items/<id>/recategorize` `{category}` (moves vault file + frontmatter); `POST /api/items/<id>/honcho-sync` (retry)
- `GET /debug` → health (scraper, transcript, honcho, yt-dlp version)

## Deployment notes (gotchas learned the hard way)

- **Vault dirs must stay `757`** — through the NFS bind chain, LXC root is squashed and only world-writable dirs work reliably (scraper, WebUI container uid 1024, syncthing). Files stay 644. Do NOT "normalize" to 755.
- Scraper and webui `chmod 757` directories they create.
- `index.html` is served from an external file (`Path.read_text()`) — do NOT embed it in webui.py as a Python string (escape corruption).
- Single-file SPA: one `<script>` block, string-aware JS balance check before deploy (`check_js_balance.py`).
- `.env` (Honcho key) is read at runtime from `/opt/quarry/.env` — **never commit it** (`.gitignore`). See operations-log 2026-07-31 for the leak incident.
- Deployment chain: `.22` → SSH root@`.13` → `pct exec 101` → pipe files into `/opt/quarry/`, `systemctl restart quarryd`.

## Dev workflow

- `check_js_balance.py index.html` — JS structural check (must print BALANCED)
- `python3 -m py_compile webui.py quarry.py`
- Deploy: pipe-through-exec (`cat > /opt/quarry/<file>` via `pct exec`), restart service, verify content (not just HTTP 200)
- `CLAUDE.md` — project context for Claude Code sessions
