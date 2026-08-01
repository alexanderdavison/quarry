# Quarry — YouTube scraper + vault seeder

## What this is
Quarry runs on Proxmox LXC 101 (192.168.1.21:5000) as `quarryd.service`, working dir `/opt/quarry/`.
It scrapes YouTube videos into an Obsidian vault and seeds Honcho memory.

## Files in this workspace (working copies — deploy happens separately)
- `webui.py` — Flask backend (372 lines). Serves `index.html`, exposes JSON API.
- `index.html` — single-file SPA (462 lines). One `<script>` block, hash routing, dark theme.
- `quarry.py` — the scraper CLI. **Deployed on the LXC as `quarry` (no extension)** with shebang `#!/opt/scraper-venv/bin/python3`. Don't change the shebang.
- `seed-vault-to-honcho.sh` — cron helper on the Hermes host that seeds vault docs into Honcho workspaces per profile.

## Backend facts
- `VAULT = "/mnt/obsidian-vault"` (NFS; category dirs each contain a `youtube/` subdir).
- `CATEGORIES` in webui.py maps id → {label, path}: sources, shared, homelab-wiki, personal-wiki, ish-d, real-estate, dental-msp, axiom-music. ish-d label is "Ish D".
- Existing endpoints: POST `/scrape` {url, category} (runs scraper, returns {ok, file, summary, output}); GET `/recent` ({scrapes:[...]}); GET `/view/<path>`; GET `/debug`; POST `/delete-scrape` {id}; POST `/api/items/<id>/recategorize` {category}; POST `/api/items/<id>/honcho-sync`.
- Every recent record has: id, title, channel, category, path (vault-relative), summary, timestamp, honcho_sync_status ("synced"|"pending"|"failed").

## Frontend facts
- `navigate(page)` switches `.page` divs (page-home, page-recent, page-library, page-categories, page-tags, page-stats, page-activity, page-settings, page-jobs, page-system-status, page-import, page-vault, page-memory). All pages have load functions since 2026-07-31 (import/vault/memory were stubs before).
- Helpers: `api(url, opts)` (fetch→json, never throws), `showToast(msg, type)`, `esc(s)` (HTML-escape), `CATEGORIES` array, `CATEGORY_LABELS` map, `selectedCategory` variable.
- Existing style: `var`, `function(){}`, string concat (no fancy ES), no template literals. **Keep this style.**
- Onclick handlers embedding dynamic values must use `encodeURIComponent(...)` (pitfall: unquoted args break).

## Scraper facts (quarry.py)
- `CATEGORY_WORKSPACE_MAP` maps category → Honcho workspace: sources/shared/homelab-wiki/personal-wiki → "hermes", real-estate → "hermes_real-estate", dental-msp → "hermes_dental-msp", axiom-music → "hermes_axiom-music", ish-d → "hermes_ish-d" (wired 2026-07-31).
- The scraper validates category against this map and dies on unknown ones.
- Reads HONCHO_API_KEY from `/opt/quarry/.env` (don't touch). Writes vault notes with chown wyandotte:wyandotte chmod 644.

## Seed script facts
- `PROFILES[...]` maps vault dir → Hermes profile: homelab-wiki→default, real-estate→real-estate, dental-msp→dental-msp, axiom-music→axiom-music, ish-d→ish-d (added 2026-07-31).

## Verification requirements (run before reporting done)
1. `python3 -m py_compile webui.py quarry.py` — must pass.
2. `bash -n seed-vault-to-honcho.sh` — must pass.
3. JS integrity: run `python3 check_js_balance.py index.html` — must print BALANCED. Single `<script>` block only (first `<script>` and last `</script>` must pair; no second `<script>` tag).
4. No dead code: after edits, no leftover fragments of replaced functions (check the specific old function bodies are gone).
5. Do not touch files other than the four above.
