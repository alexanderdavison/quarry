# Quarry — YouTube scraper + vault seeder

## What this is
Quarry runs on Proxmox LXC 101 (192.168.1.21:5000) as `quarryd.service`, working dir `/opt/quarry/`.
It scrapes YouTube videos into an Obsidian vault and seeds Honcho memory.

## Files in this workspace (working copies — deploy happens separately)
- `webui.py` — Flask backend. Serves `index.html`, exposes JSON API + NDJSON streams.
- `index.html` — single-file SPA. One `<script>` block, hash routing, dark theme.
- `quarry` — the scraper CLI (no extension, matches the deployed name) with shebang `#!/opt/scraper-venv/bin/python3`. Don't change the shebang.
- `scripts/smoke_test.sh` — API + deployed-source checks against the live LXC.
- `seed-vault-to-honcho.sh` — cron helper on the Hermes host that seeds vault docs into Honcho workspaces per profile.

## Backend facts
- `VAULT = "/mnt/obsidian-vault"` (NFS; category dirs each contain a `youtube/` subdir).
- `CATEGORIES` in webui.py maps id → {label, path}: sources, shared, homelab-wiki, personal-wiki, ish-d, real-estate, dental-msp, axiom-music. ish-d label is "Ish D".
- `CATEGORY_WORKSPACE_MAP` in webui.py mirrors the scraper's map — **keep the two in sync.** `_update_honcho(item, category_id)` derives the workspace from it (was hardcoded to `hermes` before 2026-08-01).
- Endpoints: POST `/scrape` {url, category} (**NDJSON stream**, see below); GET `/recent` ({scrapes:[...]}); GET `/api/vault`; GET `/view/<path>`; GET `/debug`; POST `/delete-scrape` {id}; POST `/api/items/<id>/recategorize` {category}; POST `/api/items/<id>/honcho-sync`; GET `/api/health`; GET+POST `/api/settings`; GET `/api/check` (alias `/api/suggest`); POST `/api/batch-scrape`.
- Every recent record has: id, title, channel, category, path (vault-relative), summary, timestamp, honcho_sync_status ("synced"|"pending"|"failed"), and since 2026-08-01 video_id + url (records written before then lack both).
- `/scrape` and `/api/batch-scrape` stream NDJSON (`application/x-ndjson`), one JSON object per line. `/scrape` yields `{type:"stage",stage,message}` then a terminal `{type:"done",...}`; `/api/batch-scrape` yields `{type:"item"|"progress"}` then `{type:"batch_done",summary}`. Both refuse duplicates (video_id already in recent.json) before running the scraper.
- `_run_scraper()` maps the scraper's `STAGE:*` marker lines to metadata/transcript/note/honcho, plus `save` from the indented `Written:` line. Success is the scraper's **final, unindented** `Written:` line — only by then has recent.json been updated. A `threading.Timer` bounds each run at `SCRAPE_TIMEOUT` (120s); `PYTHONUNBUFFERED=1` in the child env is what makes the stages arrive live.
- `/api/settings` reads/writes `/opt/quarry/settings.json` (created with defaults on first read): `default_category`, `hermes_webui_url`.

## Frontend facts
- Sidebar: CONTENT (Home, Recent, Library, Categories, Tags) / IMPORT (Batch Import) / SYSTEM (Jobs, Activity), plus a health footer. A header gear button opens Settings. Pages dropped from the sidebar (stats, settings, system-status, vault, memory) **still exist and are reachable by hash** — don't delete their divs or load functions.
- `navigate(page)` switches `.page` divs (page-home, page-recent, page-library, page-categories, page-tags, page-stats, page-activity, page-settings, page-jobs, page-system-status, page-import, page-vault, page-memory) and marks the nav item via `data-page`.
- Helpers: `api(url, opts)` (fetch→json, never throws), `streamNdjson(url, opts, onLine)` (**use this, not `api()`, for `/scrape` and `/api/batch-scrape`**), `showToast(msg, type)`, `esc(s)`, `escAttr(s)` (esc + quotes, for attribute values), `timeAgo(ts)`, `extractVideoId(u)`, `CATEGORIES` array, `CATEGORY_LABELS` map, `selectedCategory`, `appSettings`/`loadAppSettings()`/`hermesUrl()`.
- `renderRecentTable(items)` renders both the Home preview (5 rows) and the Recent page: TITLE | DESTINATION | STATUS | ADDED + hover actions.
- Existing style: `var`, `function(){}`, string concat (no fancy ES), no template literals. **Keep this style.**
- Onclick handlers embedding dynamic values must use `encodeURIComponent(...)` (pitfall: unquoted args break).
- **No bare `/` division operator in the script.** `check_js_balance.py` reads any `/` not followed by `/` or `*` as the start of a regex literal, so one stray division desyncs it and the check fails. `timeAgo()` counts by subtraction for this reason.

## Scraper facts (quarry)
- `CATEGORY_WORKSPACE_MAP` maps category → Honcho workspace: sources/shared/homelab-wiki/personal-wiki → "hermes", real-estate → "hermes_real-estate", dental-msp → "hermes_dental-msp", axiom-music → "hermes_axiom-music", ish-d → "hermes_ish-d" (wired 2026-07-31).
- The scraper validates category against this map and dies on unknown ones.
- Reads HONCHO_API_KEY from `/opt/quarry/.env` (don't touch). Writes vault notes with chown wyandotte:wyandotte chmod 644.
- Prints `STAGE:metadata` / `STAGE:transcript` / `STAGE:note` / `STAGE:honcho` before each step so webui can map the stream to stages (added 2026-08-01). It prints `Written:` **twice** — indented mid-run, then unindented as the final line; webui keys success off the unindented one.
- Note frontmatter: title, source, url, video_id, channel, date, duration, views. Records get video_id + url.

## Seed script facts
- `PROFILES[...]` maps vault dir → Hermes profile: homelab-wiki→default, real-estate→real-estate, dental-msp→dental-msp, axiom-music→axiom-music, ish-d→ish-d (added 2026-07-31).

## Verification requirements (run before reporting done)
1. `python3 -m py_compile webui.py quarry` — must pass.
2. `bash -n seed-vault-to-honcho.sh scripts/smoke_test.sh` — must pass.
3. JS integrity: run `python3 check_js_balance.py index.html` — must print BALANCED. Single `<script>` block only (first `<script>` and last `</script>` must pair; no second `<script>` tag). If node is available, also extract the script block and `node --check` it.
4. No dead code: after edits, no leftover fragments of replaced functions (check the specific old function bodies are gone).
5. Keep the function name `renderScrapeForm` — `scripts/smoke_test.sh` greps for it.
6. Do not touch files other than those listed above.
