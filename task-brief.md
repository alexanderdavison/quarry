# Quarry Lean UI — Task Brief (2026-08-01)

Implement the changes below in **/root/quarry**. Read CLAUDE.md first — it has project facts, constraints, and verification requirements. Work ONLY on these files:
- `webui.py` — Flask backend
- `index.html` — single-file SPA
- `quarry` — scraper CLI (no extension; shebang `#!/opt/scraper-venv/bin/python3` — DO NOT change)
- `scripts/smoke_test.sh` — extend if you change checked surfaces
- `CLAUDE.md` — update facts if they change

Preserve the existing visual style (dark theme, `var`/`function(){}` JS style, string concat, no template literals). Keep changes small and reversible. Do NOT delete backend endpoints — pages may leave the sidebar but routes stay.

## Current state (verified — do not re-derive)

- **Backend routes:** `/`, `/logo.svg`, POST `/scrape`, GET `/recent`, GET `/api/vault`, GET `/view/<path>`, GET `/debug`, POST `/delete-scrape`, POST `/api/items/<id>/recategorize`, POST `/api/items/<id>/honcho-sync`.
- **Records** (`/opt/quarry/recent.json`, max 50): `{id, title, channel, category, path, summary, timestamp, honcho_sync_status ("synced"|"pending"|"failed"), recategorized_at?}`. **No URL/video_id stored today** — you will add `video_id` (and `url`) going forward; old records lack them.
- **Scraper stages** (prints to stdout): metadata fetch → transcript fetch → summary → write note (`Written: <path>` line, webui parses it) → seed Honcho → update recent. Note frontmatter: title, source, url, channel, date, duration, views.
- **Smoke test currently requires:** GET / 200; `renderScrapeForm` present in HTML; `/api/vault` has ish-d + ≥8 labels; `/debug` has `ytdlp_version`; `/recent` valid JSON; py_compile both; JS balance on deployed index.html. **Keep all of these passing** (keep the function name `renderScrapeForm`).
- **Settings page is a stub** (nothing to preserve — build it fresh).
- **Jobs page** has no loader (leave as-is). **Tags page** is a placeholder (leave as-is).
- Sidebar today: Content (Home Recent Library Categories Tags Stats Activity Settings) / System (Jobs, System) / Quick Actions (Import Vault Memory).

## TASK 1 — Sidebar navigation restructure (index.html)

Final structure, exact labels:
```
CONTENT    Home, Recent, Library, Categories, Tags
IMPORT     Batch Import
SYSTEM     Jobs, Activity
```
- Remove from the sidebar: Stats, Settings, System (system-status), Import (old single-URL page), Vault, Memory.
- **Do not delete the page divs or their load functions** — pages stay reachable by hash (`#vault`, `#memory`, `#stats`, etc.). Only the sidebar links go. `navigate()` keeps working for all pages.
- The `Import` page becomes **Batch Import** (see TASK 6). Rename its nav entry; page id stays `page-import`, nav label "Batch Import", heading "Batch Import".
- Header: add a gear button aligned to the far right (`margin-left:auto`), styled as a subtle icon button (use a unicode gear `⚙` or inline SVG, ~16px, color `#88889a`). Clicking it calls `navigate('settings')`.
- Sidebar footer (after SYSTEM section, bottom of sidebar — `margin-top:auto` on the footer container): three compact health indicators, one per line:
  `● Obsidian`, `● Hermes`, `● Worker`
  Dot green (`#22c55e`) when healthy, red (`#f87171`) when not. When a service is unhealthy, the row is clickable and opens a small inline detail popover (positioned near the row): shows the service name + the `detail` string from `/api/health` + a "Open Settings" link (calls `navigate('settings')`). When healthy, the row is not clickable and shows only the name + dot. Poll `/api/health` on load and every 30s.

## TASK 2 — Backend: `/api/health`, `/api/settings`, `/api/check`, `/api/suggest` (webui.py)

- `GET /api/health` → `{"obsidian": {"ok": bool, "detail": str}, "hermes": {"ok": bool, "detail": str}, "worker": {"ok": bool, "detail": str}, "version": "2026-08-01"}`.
  - obsidian: `VAULT` exists, is dir, `os.access(VAULT, os.W_OK)`; detail = path or the failure reason.
  - hermes: reuse the existing Honcho POST check from `/debug` (same 3s timeout); detail = `"HTTP 201"` / error text.
  - worker: scraper file exists + executable; detail = path or failure reason. Also include `ytdlp_version` in the worker detail when healthy.
- `GET /api/settings` → `{"default_category": str, "hermes_webui_url": str}` loaded from `/opt/quarry/settings.json` (create with defaults `{"default_category": "sources", "hermes_webui_url": "http://192.168.1.22:8787"}` if missing — atomic write like `_write_records_atomic` pattern). `POST /api/settings` accepts partial updates (`{default_category?, hermes_webui_url?}`), validates `default_category` is in CATEGORIES and `hermes_webui_url` starts with `http`, writes atomically, returns the merged settings.
- `GET /api/check?url=...` → lightweight paste-time check:
  - Extract video ID with the same regex the scraper uses (`(?:v=|/v/|youtu\.be/|shorts/|embed/|live/)([a-zA-Z0-9_-]{11})`, or bare 11-char id). Invalid → `{"valid": false, "video_id": null}`.
  - Look through records: any record with `video_id == id` → `{"valid": true, "video_id": id, "duplicate": true, "record": {...}}`.
  - Else try yt-dlp metadata (`/opt/scraper-venv/bin/yt-dlp --skip-download --print-json --no-warnings <url>`, timeout 8s): get `id` + `channel` + `title`. Match channel against records (case-insensitive) → most common category for that channel → `suggested_category`. Also match slugified title against existing record paths (strip the leading `YYYY-MM-DD-` from the path stem, compare to `slugify(title)` from the scraper) → duplicate fallback for old records that lack `video_id`.
  - Response: `{"valid": true, "video_id": id, "duplicate": false, "suggested_category": "homelab-wiki"|null, "title": ..., "channel": ...}`.
  - Cache metadata by video_id in a module-level dict (in-memory only) to avoid repeat yt-dlp calls.
  - `/api/suggest` — same response shape; `/api/check` is the canonical endpoint, keep `/api/suggest` as an alias or drop it entirely (frontend will call `/api/check` only). Decide one name, use it.
- **Honcho workspace fix:** `_update_honcho` posts to a hardcoded `hermes` workspace. Make it derive the workspace from the category exactly like the scraper's `CATEGORY_WORKSPACE_MAP` (sources/shared/homelab-wiki/personal-wiki → hermes; ish-d → hermes_ish-d; real-estate → hermes_real-estate; dental-msp → hermes_dental-msp; axiom-music → hermes_axiom-music). Add the same map to webui.py. This fixes recategorize/honcho-sync writing to the wrong workspace for non-homelab categories.

## TASK 3 — Backend: `/scrape` streaming + duplicate guard (webui.py)

- `POST /scrape` becomes an **NDJSON stream** (Flask `Response(gen, mimetype="application/x-ndjson")`). The frontend is the only consumer.
- Before running the scraper: extract video_id from the URL; if a record already has that video_id → yield `{"type": "done", "ok": false, "duplicate": true, "record": {...}}` and stop (do NOT run the scraper, do NOT create a copy).
- Run the scraper via `subprocess.Popen([SCRAPER, url, category], stdout=PIPE, stderr=STDOUT, text=True, env={...HONCHO_API_KEY...})`. Read stdout line by line (bounded: timeout 120s total — implement by reading with a deadline or `proc.wait(120)` then drain). For each line:
  - Map scraper output to stages and yield `{"type": "stage", "stage": "...", "message": line}`:
    - `Fetching metadata...` → `metadata`
    - `Fetching transcript...` → `transcript`
    - `Writing vault note...` → `note`
    - `Seeding Honcho...` → `honcho`
    - anything else → skip (pass raw as message with stage `working` for lines like `Title:`/`Summary:` — keep noise low: yield `working` only for `Title:`, `Transcript:`, `Summary:` lines).
  - On `Written:` line: parse the vault-relative path (current code splits on `Written:`), then read the fresh record from recent.json (match by path, like the current code does) to get title/channel/summary/video_id, yield `{"type": "done", "ok": true, "file": rel, "title": ..., "channel": ..., "video_id": ..., "summary": ..., "category": category}` and terminate the stream.
  - On process exit without success: yield `{"type": "done", "ok": false, "error": <stderr tail or exit code>}`.
- Keep `"Written:"` parsing working — the scraper's final `print(f"Written: {outfile}")` line stays.

## TASK 4 — Backend: `/api/batch-scrape` (webui.py)

- `POST /api/batch-scrape` body `{"urls": [..], "category": ".."}` (max 20 urls). Validate category. NDJSON stream, one item at a time, sequentially:
  - For each url: extract video_id. Invalid → `{"type": "item", "index": i, "url": url, "status": "invalid", "error": "not a YouTube URL"}`.
  - Duplicate (record with video_id) → `{"type": "item", "index": i, "url": url, "status": "duplicate", "title": rec.title, "record": rec}` — do not process.
  - Otherwise run the scraper (same Popen pattern, 120s each); yield `{"type": "item", "index": i, "url": url, "status": "processing", "title": ...}` when it starts, then on success `{"type": "item", ..., "status": "done", "title": ..., "file": ...}` or on failure `{"type": "item", ..., "status": "failed", "error": ...}`.
  - Between items yield `{"type": "progress", "done": n, "total": N}`.
  - Final line: `{"type": "batch_done", "summary": {"done": n, "failed": n, "duplicate": n, "invalid": n}}`.
- No background jobs, no queue state — the HTTP request stays open and streams. (Single-user tool, Flask dev server handles this fine.)

## TASK 5 — Scraper: video_id in records + note (quarry)

- `update_recent()`: add `"video_id": video_id` and `"url": url` to the record dict (keep existing keys).
- `write_vault_note()`: add `video_id: <id>` line to the frontmatter (pass video_id as a parameter).
- Add explicit stage marker lines to stdout so webui's stage mapping is robust (before each step's existing print):
  - before metadata fetch: `print("STAGE:metadata")`
  - before transcript fetch: `print("STAGE:transcript")`
  - before writing note: `print("STAGE:note")`
  - before seeding honcho: `print("STAGE:honcho")`
- webui should match these `STAGE:` lines in preference to text heuristics (TASK 3), falling back to text matching if absent.
- Do NOT change the `Written:` line format, the note layout, the transcript handling, or the Honcho payload.

## TASK 6 — Frontend: Home page (index.html)

Keep current layout. Changes:
- Button label: `Transcribe & Save` → `Process`. Disabled state text: `Processing...`. (Keep the function name `renderScrapeForm` and the element ids — smoke test greps `renderScrapeForm`.)
- On paste (input event, debounced ~500ms): call `GET /api/check?url=<encoded>`. If `duplicate` → show a compact inline notice under the input: `Already processed  [Open]` (Open links to `/view/<record.path>` via `viewUrl`, target _blank) and disable Process until the URL changes. If `suggested_category` present and user has not manually clicked a pill since this paste → highlight that pill (add a subtle ring/border, e.g. `box-shadow: 0 0 0 1px #8b5cf6`) and show a tiny `Suggested: Homelab` label next to the pills row. Manual pill click clears the suggestion state.
- Processing feedback: a single compact status area directly under the capture area (replaces the current inline result panel while running). Shows the stage sequence as text: `Extracting transcript → Creating note → Saving to Obsidian → Indexing Hermes` — the active stage is highlighted (e.g. bright color + underline) and completed stages dimmed. Render from the streamed `stage` values (metadata → "Extracting transcript", transcript → same, note → "Creating note", save → "Saving to Obsidian", honcho → "Indexing Hermes"). If the stream ends before honcho (scraper skips it), just stop advancing.
  - Implement the stream read with `fetch` + `response.body.getReader()` + `TextDecoder`, splitting on newlines. The existing `api()` helper returns JSON — do NOT use it for `/scrape` and `/api/batch-scrape`; write a `streamNdjson(url, opts, onLine)` helper.
- Success: compact green line: `✓ Added to Homelab` (destination label from the chosen category) + actions `Open Note` (viewUrl link) · `Ask Hermes` (link to `hermes_webui_url` from `/api/settings`, target _blank). Title shown small above the line (keep the existing "View note" behavior as "Open Note").
- Failure: `Hermes indexing failed` (or the stage name that was active when the stream died, e.g. `Saving to Obsidian failed`) + error detail small + `[Retry]` button that re-submits the same URL.
- Duplicate at submit time (server-side guard): render the `Already processed [Open]` state (same as paste-time).
- Keep the Recent table below the form (TASK 7 rendering).

## TASK 7 — Frontend: Recent table (index.html)

Both the Home Recent table and the Recent page table use the same renderer with these columns:
`TITLE | DESTINATION | STATUS | ADDED` (+ hidden action column on hover).
- Title: clickable → opens the note (`viewUrl(path)`, target _blank). Show channel as a small sub-line under the title (keep it compact).
- Destination: `CATEGORY_LABELS[s.category]`.
- Status: badge mapping `honcho_sync_status`: synced → `Ready` (green), pending → `Processing` (amber), failed → `Failed` (red).
- Added: relative time from `timestamp` (`12m ago`, `1h ago`, `2d ago` — write a small `timeAgo(ts)` helper).
- Hover actions (hidden by default: `opacity:0` on the actions cell, `opacity:1` on `tr:hover`): `Open Note · Ask Hermes · Move · More`.
  - Open Note / Ask Hermes: same as TASK 6.
  - Move: existing `openMoveModal(id, cat)`.
  - More: a small dropdown (simple absolutely-positioned div toggled by click, close on outside click) containing `Delete` (existing `deleteRecent`) and, when `honcho_sync_status !== "synced"`, `Retry Honcho` (existing `retryHonchoSync`).
- Keep the Recent page's category filter select. Home table shows the 5 most recent.

## TASK 8 — Frontend: Batch Import page (index.html, page-import)

Replace `loadImport()`:
- Textarea (placeholder `Paste one YouTube URL per line...`) + the existing pills (`Save to:` / `renderPills`) + a `Process N Videos` primary button (label reflects valid count; disabled when 0 valid).
- Live counts line under the textarea: `3 valid links · 1 duplicate · 0 invalid` recomputed on input. Validation = extractable video ID (same regex) + host is youtube.com or youtu.be; duplicate = matches a record's video_id or a record path slug (client-side against `scrapesData` — load `/recent` on page entry).
- On Process: `POST /api/batch-scrape` streamed via the NDJSON helper. Render a per-item list (url + title once known) with status: `Queued` (before its item line arrives — derive from the requested order), `Processing`, `Ready`, `Failed`, `Skipped` (invalid/duplicate). Statuses update live as lines stream. Invalid/duplicate items show a small reason.
- Failed items get a `Retry` button that re-submits ONLY those urls (build a second batch from failed entries and re-run the same flow; successful items are not reprocessed).
- Keep it lean: no spreadsheet editing, no per-item destination.

## TASK 9 — Frontend: Settings page (gear) (index.html)

Replace the stub `loadSettings()` with a compact, single-scroll panel. No fake controls — everything shown must be real:
- **Default destination**: select of the 8 categories, loaded from `GET /api/settings` (`default_category`), saved via `POST /api/settings` on change. On app load, initialize `selectedCategory` from the saved default (fetch settings in `loadHome` and before `renderPills`).
- **Hermes WebUI URL**: text input, saved via `POST /api/settings` (used by Ask Hermes links).
- **Obsidian**: vault path + mount status (from `/api/health` — green/red + detail).
- **Hermes (Honcho)**: endpoint (show `HONCHO_URL` base — display-only) + status from health.
- **Transcript provider**: display-only line (`youtube-transcript-api`).
- **Worker & queue**: display-only — scraper path, yt-dlp version, scrape count. Retry behavior: display-only note ("Retry via item actions").
- **Category → folder mappings**: read-only table (CATEGORIES labels + paths).
- **Service health & version**: from `/api/health` + `version`.
Keep the page ~1 screen, no tabs (the old stub had none — build simple).

## Verification (run before reporting done — all must pass)

1. `python3 -m py_compile webui.py quarry` (quarry is the scraper; compile with its shebang venv python if possible, else system python3 — it uses `str | None` syntax which needs 3.10+, system python3.12 is fine).
2. `python3 check_js_balance.py index.html` → BALANCED (from the repo root).
3. If node is available: extract the script block and `node --check` it.
4. `bash -n scripts/smoke_test.sh`.
5. No leftover dead code from replaced functions — grep for old labels (`Transcribe &amp; Save`, old nav items in the sidebar HTML, `Suggested:` stub leftovers) and confirm the old sidebar links are gone.
6. Update `scripts/smoke_test.sh` if any checked surface changed (it currently greps `renderScrapeForm` — keep that function name so it stays green; ADD checks: `/api/health` returns obsidian/hermes/worker keys, `/api/check?url=notaurl` returns `valid:false`, `/api/settings` returns default_category). Do not remove existing checks.
7. Print a concise diff summary: files changed, endpoints added/changed, verification results.

## Do not

- Do not touch `seed-vault-to-honcho.sh` (not in this scope).
- Do not change the scraper's `Written:` output format, note layout, or Honcho payload.
- Do not delete any backend endpoint.
- Do not add dependencies, npm packages, or new files to `/opt/quarry` (settings.json is created at runtime by the backend — that's fine).
- Do not deploy anything — editing files in `/root/quarry` only. Deployment is handled separately.
