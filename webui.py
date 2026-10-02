#!/usr/bin/env python3
"""Quarry — YouTube scraper + memory seeder. Single-file app."""

import subprocess, os, html, json, uuid, shutil, tempfile, re, threading, time, urllib.error, urllib.request
from pathlib import Path
from datetime import datetime, timezone
from flask import Flask, request, render_template_string, jsonify, send_file, Response

app = Flask(__name__)
VAULT = "/mnt/obsidian-vault"
SCRAPER = "/opt/quarry/quarry"
YTDLP = "/opt/scraper-venv/bin/yt-dlp"
RECENT_FILE = "/opt/quarry/recent.json"
SETTINGS_FILE = "/opt/quarry/settings.json"
BACKUP_DIR = "/opt/quarry/backups"
LOGO_PATH = "/opt/quarry/quarry-logo.png"
HONCHO_BASE = "http://192.168.1.23:8000"
HONCHO_URL = f"{HONCHO_BASE}/v3/workspaces/hermes/conclusions"
HEALTH_VERSION = "2026-08-01"
SCRAPE_TIMEOUT = 120
BATCH_MAX_URLS = 20

# Category -> Honcho workspace: see WORKSPACE_MAP_FILE (single source of truth).


WORKSPACE_MAP_FILE = "/mnt/obsidian-vault/.quarry/categories.json"


def _load_workspace_map(default):
    """Category -> Honcho workspace, from ONE vault-hosted file shared by Quarry's two
    entry points and the daily distill job on .22 (they had drifted apart). Falls back
    to the built-in literal if the file is missing or unreadable: a config read must
    never break ingest. Never raises."""
    try:
        with open(WORKSPACE_MAP_FILE) as fh:
            m = (json.load(fh) or {}).get("workspace_map") or {}
        clean = {k: v for k, v in m.items() if isinstance(k, str) and isinstance(v, str) and v}
        if clean:
            return clean
    except Exception:
        pass
    return dict(default)


_DEFAULT_WORKSPACE_MAP = {
    "sources":         "hermes",
    "shared":          "hermes",
    "homelab-wiki":    "hermes",
    "personal-wiki":   "hermes",
    "ish-d":           "hermes_ish-d",
    "real-estate":     "hermes_real-estate",
    "relaystone-systems": "hermes_relaystone-systems",
    "axiom-music":     "hermes_axiom-music",
    "videoprod":       "hermes",
}

CATEGORY_WORKSPACE_MAP = _load_workspace_map(_DEFAULT_WORKSPACE_MAP)

def _read_env_key(name):
    """Read a KEY=value line from /opt/quarry/.env (multi-line safe)."""
    try:
        for line in Path("/opt/quarry/.env").read_text().splitlines():
            line = line.strip()
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return ""

DEEPSEEK_BASE = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
DEEPSEEK_KEY = os.environ.get("DEEPSEEK_API_KEY", "") or _read_env_key("DEEPSEEK_API_KEY")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
HONCHO_KEY = os.environ.get("HONCHO_API_KEY", "") or _read_env_key("HONCHO_API_KEY")

DEFAULT_SETTINGS = {
    "default_category": "sources",
    "hermes_webui_url": "http://192.168.1.22:8787",
}

CATEGORIES = {
    "sources":     {"label": "Sources",     "path": "sources/youtube/"},
    "shared":      {"label": "Shared",      "path": "shared/youtube/"},
    "homelab-wiki":{"label": "homelab-wiki","path": "homelab-wiki/youtube/"},
    "personal-wiki":{"label":"Personal",    "path": "personal-wiki/youtube/"},
    "ish-d":       {"label": "Ish D",       "path": "ish-d/youtube/"},
    "real-estate": {"label": "Real Estate",  "path": "real-estate/youtube/"},
    "relaystone-systems": {"label": "Relay Stone Systems", "path": "relaystone-systems/youtube/"},
    "axiom-music": {"label": "Axiom",        "path": "axiom-music/youtube/"},
    "videoprod":   {"label": "videoprod",  "path": "videoprod/youtube/"},
}

# ── Helpers ────────────────────────────────────────────────────

def _load_records():
    try:
        with open(RECENT_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def _write_records_atomic(records):
    Path(BACKUP_DIR).mkdir(parents=True, exist_ok=True)
    bpath = Path(BACKUP_DIR) / f"recent-{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    try:
        if Path(RECENT_FILE).exists():
            shutil.copy2(RECENT_FILE, bpath)
    except Exception:
        pass
    fd, tmp = tempfile.mkstemp(dir=str(Path(RECENT_FILE).parent))
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(records, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, RECENT_FILE)
    except Exception:
        if Path(tmp).exists(): Path(tmp).unlink()
        raise

def _write_json_atomic(path, payload):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent))
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, str(p))
    except Exception:
        if Path(tmp).exists(): Path(tmp).unlink()
        raise

def _load_settings():
    """Read settings.json, creating it with defaults on first use."""
    try:
        with open(SETTINGS_FILE) as f:
            stored = json.load(f)
        if not isinstance(stored, dict):
            stored = {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        stored = None
    merged = dict(DEFAULT_SETTINGS)
    if stored is None:
        try:
            _write_json_atomic(SETTINGS_FILE, merged)
        except Exception:
            pass
        return merged
    for k in DEFAULT_SETTINGS:
        v = stored.get(k)
        if isinstance(v, str) and v.strip():
            merged[k] = v.strip()
    return merged

# ── Video id / slug (same rules as the scraper) ────────────────

_VID_PATTERNS = [
    r'(?:v=|/v/|youtu\.be/|shorts/|embed/|live/)([a-zA-Z0-9_-]{11})',
    r'^([a-zA-Z0-9_-]{11})$',
]

def extract_video_id(url):
    url = (url or "").strip()
    for p in _VID_PATTERNS:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return None

def slugify(text):
    slug = re.sub(r'[^a-z0-9]+', '-', (text or "").lower()).strip('-')
    return slug[:80] or "untitled"

def _path_slug(rec_path):
    """'homelab-wiki/youtube/2026-07-31-some-title.md' -> 'some-title'"""
    stem = Path(rec_path or "").stem
    return re.sub(r'^\d{4}-\d{2}-\d{2}-', '', stem)

def _find_by_video_id(records, video_id):
    if not video_id:
        return None
    for r in records:
        if r.get("video_id") == video_id:
            return r
        u = r.get("url") or ""
        if u and extract_video_id(u) == video_id:
            return r
    return None

def _find_by_title_slug(records, title):
    """Duplicate fallback for legacy records written before video_id existed."""
    if not title:
        return None
    slug = slugify(title)
    for r in records:
        if r.get("path") and _path_slug(r["path"]) == slug:
            return r
    return None

def _suggest_category(records, channel):
    """Most common category previously used for this channel."""
    if not channel:
        return None
    want = channel.strip().lower()
    counts = {}
    for r in records:
        if (r.get("channel") or "").strip().lower() != want:
            continue
        cat = r.get("category")
        if cat in CATEGORIES:
            counts[cat] = counts.get(cat, 0) + 1
    if not counts:
        return None
    return max(counts.items(), key=lambda kv: kv[1])[0]

_META_CACHE = {}

def _ytdlp_meta(url, video_id):
    """Cheap metadata probe for paste-time checks. Cached in-memory by video id."""
    if video_id in _META_CACHE:
        return _META_CACHE[video_id]
    meta = {}
    try:
        r = subprocess.run(
            [YTDLP, "--skip-download", "--print-json", "--no-warnings", url],
            capture_output=True, text=True, timeout=8,
        )
        if r.returncode == 0 and r.stdout.strip():
            raw = json.loads(r.stdout)
            meta = {
                "id": raw.get("id") or video_id,
                "title": raw.get("title") or "",
                "channel": raw.get("channel") or raw.get("uploader") or "",
            }
    except Exception:
        meta = {}
    if meta:
        _META_CACHE[video_id] = meta
    return meta

def _preflight_duplicate(url, video_id):
    """Dup check for ingest paths: exact video_id first, then legacy slug fallback
    (records written before video_id existed)."""
    if not video_id:
        return None
    records = _load_records()
    dup = _find_by_video_id(records, video_id)
    if dup:
        return dup
    meta = _ytdlp_meta(url, video_id)
    return _find_by_title_slug(records, meta.get("title", ""))

# ── Scraper streaming ──────────────────────────────────────────

_STAGE_MARKERS = {
    "STAGE:metadata":   "metadata",
    "STAGE:transcript": "transcript",
    "STAGE:note":       "note",
    "STAGE:honcho":     "honcho",
}
_STAGE_TEXT = [
    ("Fetching metadata",  "metadata"),
    ("Fetching transcript","transcript"),
    ("Writing vault note", "note"),
    ("Seeding Honcho",     "honcho"),
]
_WORKING_PREFIXES = ("Title:", "Transcript:", "Summary:")

def _stage_for(line, saw_markers):
    s = line.strip()
    if s in _STAGE_MARKERS:
        return _STAGE_MARKERS[s]
    # The indented "  Written: <relpath>" line means the note hit the vault.
    if s.startswith("Written:"):
        return "save"
    if not saw_markers:
        for text, stage in _STAGE_TEXT:
            if text in s:
                return stage
    for w in _WORKING_PREFIXES:
        if s.startswith(w):
            return "working"
    return None

def _scraper_env():
    # PYTHONUNBUFFERED keeps the child's stdout line-flushed through the pipe,
    # which is what makes the stage stream arrive live instead of all at once.
    return {**os.environ,
            "HONCHO_API_KEY": os.environ.get("HONCHO_API_KEY", ""),
            "PYTHONUNBUFFERED": "1"}

def _run_scraper(url, category, timeout=SCRAPE_TIMEOUT):
    """Yield {'kind': 'stage'|'ok'|'error', ...} while the scraper runs."""
    try:
        proc = subprocess.Popen(
            [SCRAPER, url, category],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, env=_scraper_env(),
        )
    except Exception as e:
        yield {"kind": "error", "error": str(e)}
        return
    killer = threading.Timer(timeout, proc.kill)
    killer.start()
    rel = None
    tail = []
    saw_markers = False
    try:
        for raw in proc.stdout:
            line = raw.rstrip("\r\n")
            if not line.strip():
                continue
            if line.strip() not in _STAGE_MARKERS:
                tail.append(line.strip())
                if len(tail) > 20:
                    tail.pop(0)
            # Only the scraper's final, unindented "Written:" line is the
            # success signal — by then recent.json has already been updated.
            if line.startswith("Written:"):
                rel = line.split("Written:", 1)[1].strip().replace(VAULT, "").lstrip("/")
                continue
            if line.strip() in _STAGE_MARKERS:
                saw_markers = True
            stage = _stage_for(line, saw_markers)
            if stage:
                yield {"kind": "stage", "stage": stage, "message": line.strip()}
    finally:
        killer.cancel()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
    if rel:
        yield {"kind": "ok", "file": rel}
    else:
        rc = proc.returncode
        if rc is not None and rc < 0:
            err = f"scraper killed (timeout after {timeout}s)"
        else:
            err = "\n".join(tail[-5:]).strip() or f"Exit {rc}"
        yield {"kind": "error", "error": err}

def _record_for_path(rel):
    for r in _load_records():
        if r.get("path") == rel:
            return r
    return None


# ── Same-time distillation ─────────────────────────────────────

# Coverage knobs. The 2026-09 pipeline read only the FIRST 6000 chars of a transcript,
# asked for "3-5" points and hard-stopped at five — an 18-minute video advertising
# "eight moves" distilled to one. Now every chunk is mined, the video's own promised
# structure is extracted first as a skeleton, and nothing is truncated to five.
DISTILL_CHUNK_CHARS = 24000    # transcript chars per LLM call (~20 min of speech)
DISTILL_CHUNK_OVERLAP = 600    # overlap, so a point split across a boundary survives
DISTILL_MAX_CHUNKS = 10        # ceiling — beyond this the tail is left to the daily sweep
DISTILL_MAX_POINTS = 80        # sanity ceiling, NOT a summary cap
DISTILL_MAX_TOKENS = 6000      # output budget per call (was 500 — it truncated the tail)

_COUNT_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
                "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}
_STRUCTURE_UNITS = ("moves", "steps", "stages", "things", "items", "tips", "ways",
                    "lessons", "rules", "phases", "pillars", "questions", "mistakes",
                    "reasons", "keys", "components", "elements")


def _stated_count(*texts):
    """'...these eight specific moves' -> (8, 'moves'); None when no structure is promised.

    Drives the skeleton pass. A video that advertises eight items is exactly the case the
    old distiller collapsed into a single bullet."""
    blob = " ".join(t for t in texts if t)[:4000].lower()
    nums = "|".join(_COUNT_WORDS)
    pat = re.compile(r"\b(" + nums + r"|\d{1,2})\s+(?:[a-z-]+\s+){0,2}?("
                     + "|".join(_STRUCTURE_UNITS) + r")\b")
    m = pat.search(blob)
    if not m:
        return None
    raw, unit = m.group(1), m.group(2)
    n = int(raw) if raw.isdigit() else _COUNT_WORDS[raw]
    return (n, unit) if 2 <= n <= 20 else None


def _chunk_transcript(body, size=DISTILL_CHUNK_CHARS, overlap=DISTILL_CHUNK_OVERLAP,
                      max_chunks=DISTILL_MAX_CHUNKS):
    """Split a transcript into line-aligned chunks so none of it is never read."""
    body = (body or "").strip()
    if not body:
        return []
    if len(body) <= size:
        return [body]
    chunks, start = [], 0
    while start < len(body) and len(chunks) < max_chunks:
        end = min(len(body), start + size)
        if end < len(body):
            nl = body.rfind("\n", start + size // 2, end)
            if nl > 0:
                end = nl
        chunks.append(body[start:end])
        if end >= len(body):
            break
        start = max(end - overlap, start + 1)
    return chunks


def _norm_point(text):
    """Normalise a bullet for de-duplication, dropping any leading list numbering."""
    text = re.sub(r"^\s*\d+\s*[.)]\s*", "", (text or ""))
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _merge_points(points, fresh, cap=DISTILL_MAX_POINTS):
    """Append bullets, dropping the near-duplicates the chunk overlap produces."""
    seen = {_norm_point(p) for p in points}
    for pt in fresh:
        if len(points) >= cap:
            break
        key = _norm_point(pt)
        if len(key) < 25:
            continue
        if any(key in s or s in key for s in seen if len(s) >= 25):
            continue
        points.append(pt)
        seen.add(key)
    return points


def _deepseek_bullets(prompt, timeout=300):
    """One DeepSeek call -> (bullets, error). Never raises.

    NOTE: deepseek-v4-flash bills its reasoning tokens out of the SAME max_tokens budget,
    so an undersized budget returns an EMPTY completion with finish_reason=length rather
    than a short one (~1.6k reasoning tokens observed per call). Do not lower
    DISTILL_MAX_TOKENS toward the expected answer length."""
    if not DEEPSEEK_KEY:
        return [], "no deepseek key"
    payload = json.dumps({
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": "You extract concise key points from video transcripts. Output plain bullet lines only."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2, "max_tokens": DISTILL_MAX_TOKENS,
    }).encode()
    req = urllib.request.Request(
        f"{DEEPSEEK_BASE}/chat/completions", data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {DEEPSEEK_KEY}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        choice = (data.get("choices") or [{}])[0]
        out = (choice.get("message", {}).get("content") or "").strip()
        if not out:
            usage = data.get("usage", {}) or {}
            return [], (f"empty completion (finish_reason={choice.get('finish_reason')}, "
                        f"reasoning={usage.get('completion_tokens_details', {}).get('reasoning_tokens')} tokens)")
    except Exception as e:
        return [], f"{type(e).__name__} {str(e)[:80]}"
    bullets = []
    for line in out.splitlines():
        line = line.strip().lstrip("-*•").strip()
        if line and len(line) > 8 and not line.lower().startswith(("key points", "here", "section ")):
            bullets.append(line)
    return bullets, None


def _outline_points(title, description, body, n, unit):
    """Skeleton pass: the video's own n items, one bullet each, in the speaker's order."""
    prompt = (
        f"This video states that it covers {n} {unit}.\n\n"
        f"Title: {title}\nDescription: {(description or '')[:1500]}\n\n"
        f"Transcript:\n{body[:DISTILL_CHUNK_CHARS * 2]}\n\n"
        f"List those {n} {unit} in the order the speaker gives them. One bullet each, "
        f"starting with the item's own number and name, then a short gloss of what he says "
        f"about it. Never merge two {unit} into one bullet and never add a {unit} he did "
        f"not give. Bullets only, no preamble, no commentary."
    )
    return _deepseek_bullets(prompt)


def _extract_points(title, channel, description, body):
    """Full-coverage extraction -> (bullets in video order, errors).

    Order: the skeleton (the video's promised items) first, then every detail bullet the
    transcript yields. A failed chunk is skipped rather than aborting the note, and its
    reason lands in `errors` so partial coverage is visible instead of silent."""
    points, errors = [], []
    stated = _stated_count(description, title, body[:1500])
    if stated:
        n, unit = stated
        skeleton, err = _outline_points(title, description, body, n, unit)
        if err:
            errors.append(f"skeleton: {err}")
        _merge_points(points, skeleton)
    chunks = _chunk_transcript(body)
    for i, chunk in enumerate(chunks, 1):
        where = "" if len(chunks) == 1 else f" (section {i} of {len(chunks)})"
        prompt = (
            f"You are mining a YouTube video transcript into a knowledge base{where}.\n\n"
            f"Title: {title}\nChannel: {channel}\n"
            f"Description: {(description or '')[:1500]}\n\n"
            f"Transcript:\n{chunk}\n\n"
            "Extract EVERY distinct point the speaker makes IN THIS TEXT, in the order "
            "they make them. Do not summarise the video as a whole — mine this text.\n"
            "Rules:\n"
            "- One bullet per distinct point, starting with '- '.\n"
            "- If the video or its description states a number of items (e.g. \"eight "
            "moves\", \"five stages\", \"3 things\"), each item MUST get its own bullet. "
            "Never merge two items into one bullet.\n"
            "- Keep each bullet under 30 words, but keep the specifics: numbers, prices, "
            "tool names, steps.\n"
            "- Include every point you can find in this text. More bullets beats a "
            "missing point.\n"
            "- Skip housekeeping: like/subscribe asks, sponsor reads, channel plugs, links "
            "to other videos, and personal asides with no advice in them.\n"
            "- Do not split one idea across several bullets and do not pad.\n"
            "- Output bullets only: no preamble, no headers, no commentary."
        )
        fresh, err = _deepseek_bullets(prompt)
        if err:
            errors.append(f"section {i}: {err}")
            continue
        _merge_points(points, fresh)
    return points, errors


def _ensure_peers(workspace):
    """Register the peers a conclusion/message write needs, BEFORE writing.

    A write whose peer is missing returns 404 — and the first such 404 has been observed
    to wedge the conclusions endpoint server-side: every later write hangs, on every
    workspace, until honcho-api is restarted, while /health keeps answering 200.
    POST /peers is idempotent. Never raises (the writer reports the real outcome)."""
    for peer in ("hermes", "ishmael"):
        try:
            preq = urllib.request.Request(
                f"{HONCHO_BASE}/v3/workspaces/{workspace}/peers",
                data=json.dumps({"name": peer}).encode(),
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {HONCHO_KEY}"},
                method="POST")
            with urllib.request.urlopen(preq, timeout=45):
                pass
        except Exception:
            pass

def _post_conclusion(workspace, title, rel, points):
    """POST a distilled conclusion; self-heal missing peers. Returns (ok, err)."""
    content = (f"Quarry distilled video knowledge: {title}. "
               f"Key points: {' | '.join(points[:12])} (vault: {rel})")
    payload = json.dumps({"conclusions": [{
        "content": content[:1200], "observer_id": "hermes", "observed_id": "ishmael",
    }]}).encode()

    def post():
        req = urllib.request.Request(
            f"{HONCHO_BASE}/v3/workspaces/{workspace}/conclusions", data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {HONCHO_KEY}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                return resp.status in (200, 201), None
        except urllib.error.HTTPError as e:
            return False, e.read().decode()[:150]
        except Exception as e:
            return False, str(e)[:100]

    _ensure_peers(workspace)
    ok, err = False, None
    for attempt in range(3):
        ok, err = post()
        if ok:
            break
        if err and "not found in workspace" in err:
            _ensure_peers(workspace)   # never let the 404 path reach the endpoint again
        if attempt < 2:
            time.sleep(5 * (attempt + 1))
    return ok, err


def _index_upsert(category, filename, title, date, channel, points):
    """Upsert one video section into {category}/youtube/_knowledge-index.md.
    Keyed by heading; prunes sections whose note file is gone. Never raises."""
    try:
        idx = Path(VAULT) / category / "youtube" / "_knowledge-index.md"
        header = ["# Knowledge Index — " + (CATEGORIES.get(category, {}).get("label") or category),
                  "", "Maintained by Quarry (same-time distillation) + the daily sweep job.", ""]
        sections, order = {}, []
        if idx.exists():
            lines = idx.read_text().splitlines()
            first = next((i for i, ln in enumerate(lines) if ln.startswith("## ")), None)
            if first is not None:
                header = lines[:first] or header
                cur = None
                for ln in lines[first:]:
                    if ln.startswith("## "):
                        cur = ln; sections[cur] = [ln]; order.append(cur)
                    elif cur is not None:
                        sections[cur].append(ln)
        head = f"## {title} — {date}"
        sec = [head, f"- Channel: {channel} · [full note]({filename})"] + [f"- {pt}" for pt in points]
        if head in sections:
            sections[head] = sec
        else:
            sections[head] = sec
            order.insert(0, head)
        keep = []
        for h in order:
            fn = None
            for ln in sections[h]:
                m = re.search(r"\[full note\]\(([^)]+)\)", ln)
                if m:
                    fn = m.group(1); break
            if fn is None or (idx.parent / fn).exists():
                keep.append(h)
        out = list(header)
        if out and out[-1] != "":
            out.append("")
        for h in keep:
            out.extend(sections[h])
            out.append("")
        idx.parent.mkdir(parents=True, exist_ok=True)
        idx.write_text("\n".join(out).rstrip() + "\n")
        return True, None
    except Exception as e:
        return False, str(e)[:120]


def _mark_distilled(p, text):
    """Add distilled: true + distilled_at to the note frontmatter. Never raises."""
    try:
        if "distilled: true" in text[:500]:
            return
        m = re.match(r"^---\n(.*?)\n---", text, re.S)
        if not m:
            return
        now = datetime.now().astimezone().isoformat()
        lines = m.group(1).splitlines()
        nl, has_d = [], False
        for l in lines:
            s = l.strip()
            if s.startswith("distilled:"):
                nl.append("distilled: true"); has_d = True
            elif s.startswith("distilled_at:"):
                nl.append(f"distilled_at: {now}")
            else:
                nl.append(l)
        if not has_d:
            nl.append("distilled: true")
            nl.append(f"distilled_at: {now}")
        p.write_text(f"---\n" + "\n".join(nl) + f"\n---" + text[m.end():])
    except Exception:
        pass



def _post_message(workspace, category, title, rel, points):
    """Write the distilled knowledge as a MESSAGE as well as a conclusion.

    Honcho builds a peer's representation — what the agent actually KNOWS — from
    messages. Conclusions are inert memory atoms: searchable, never known. Writing only
    a conclusion is how mined knowledge ends up sleeping. POST .../sessions/<id>/messages
    auto-creates the session (verified 2026-09-26, HTTP 201). Returns (ok, err)."""
    NL = chr(10)
    content = (f"Vault knowledge — {title}" + NL + NL
               + NL.join(f"- {p}" for p in points[:12])
               + NL + NL + f"(source note: {rel})")
    try:
        payload = json.dumps({"messages": [{"peer_id": "hermes", "content": content[:4000]}]}).encode()
        req = urllib.request.Request(
            f"{HONCHO_BASE}/v3/workspaces/{workspace}/sessions/vault-{category}/messages",
            data=payload,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {HONCHO_KEY}"},
            method="POST")
        with urllib.request.urlopen(req, timeout=45) as resp:
            return resp.status in (200, 201), None
    except urllib.error.HTTPError as e:
        return False, e.read().decode()[:150]
    except Exception as e:
        return False, str(e)[:100]


def _inject_key_points(p, points):
    """Put the distilled points INTO the note, idempotently.

    They previously existed only in {category}/youtube/_knowledge-index.md, so reaching
    five facts cost a full 800-line transcript read. Never raises."""
    try:
        text = p.read_text()
        NL = chr(10)
        block = "## Key Points" + NL + NL + NL.join("- " + pt for pt in points) + NL + NL
        if "## Key Points" in text:
            keep, skipping = [], False
            for ln in text.split(NL):
                if ln.strip() == "## Key Points":
                    skipping = True
                    continue
                if skipping and ln.startswith("## "):
                    skipping = False
                if not skipping:
                    keep.append(ln)
            text = NL.join(keep)
        if "## Description" in text:
            new = text.replace("## Description", block + "## Description", 1)
        else:
            new = text.rstrip() + NL + NL + block
        if new != text:
            p.write_text(new)
        return True
    except Exception:
        return False


def _distill_note(rel, category):
    """Same-time distillation: key points -> index upsert -> Honcho conclusion -> marker.
    Returns (ok, message). Never raises — failures just leave the note for the daily sweep."""
    try:
        p = Path(VAULT) / rel
        if not p.exists():
            return False, "note missing"
        text = p.read_text()
        meta = {}
        m = re.match(r"^---\n(.*?)\n---", text, re.S)
        if m:
            for line in m.group(1).splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip().strip('"')
        body = text[m.end():] if m else text
        title = meta.get("title") or p.stem
        if not DEEPSEEK_KEY:
            return False, "no deepseek key"
        points, derrs = _extract_points(title, meta.get("channel", ""),
                                       meta.get("description", ""), body)
        if not points:
            return False, "no points extracted" + (f" ({'; '.join(derrs)})" if derrs else "")
        iok, ierr = _index_upsert(category, p.name, title, meta.get("date", ""), meta.get("channel", ""), points)
        workspace = CATEGORY_WORKSPACE_MAP.get(category, "hermes")
        hok, herr = _post_conclusion(workspace, title, rel, points)
        _mark_distilled(p, text)        # rewrites the note from `text`: run FIRST
        _inject_key_points(p, points)   # then put the points in the note body
        mok, merr = _post_message(workspace, category, title, rel, points)
        partial = f", {len(derrs)} section(s) failed ({'; '.join(derrs)})" if derrs else ""
        return True, f"{len(points)} points, index={'ok' if iok else ierr}, honcho={'ok' if hok else herr}, msg={'ok' if mok else merr}{partial}"
    except Exception as e:
        return False, str(e)[:120]

def _ndjson(obj):
    return json.dumps(obj) + "\n"

def _migrate_ids():
    records = _load_records()
    changed = False
    for r in records:
        if not r.get("id"):
            r["id"] = str(uuid.uuid4())
            changed = True
        if "honcho_sync_status" not in r:
            r["honcho_sync_status"] = "synced"
    if changed and records:
        _write_records_atomic(records)
    return records

def _find_record(records, item_id):
    for r in records:
        if r.get("id") == item_id:
            return r
    return None

def _update_honcho(item, category_id):
    """Post a conclusion to the workspace that owns `category_id`."""
    key = os.environ.get("HONCHO_API_KEY", "")
    if not key:
        return False, "no honcho key"
    category_name = CATEGORIES.get(category_id, {}).get("label", category_id)
    workspace = CATEGORY_WORKSPACE_MAP.get(category_id, "hermes")
    url = f"{HONCHO_BASE}/v3/workspaces/{workspace}/conclusions"
    content = f"Quarry scraped video: {item.get('title', 'Untitled')} from channel {item.get('channel', 'unknown')} in category {category_name}"
    try:
        import urllib.request
        payload = json.dumps({"conclusions": [{"content": content[:500], "observer_id": "hermes", "observed_id": "ishmael"}]}).encode()
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status in (200, 201), None
    except Exception as e:
        return False, str(e)[:80]

def _update_note_frontmatter(full_path, category_id):
    p = Path(full_path)
    if not p.exists():
        return False, "not found"
    try:
        content = p.read_text()
    except Exception as e:
        return False, f"read: {e}"
    if not content.startswith("---"):
        return False, "no frontmatter"
    fe = content.find("---", 3)
    if fe < 0:
        return False, "unclosed"
    fm = content[3:fe]
    body = content[fe + 3:]
    now = datetime.now().astimezone().isoformat()
    lines = fm.split("\n")
    nl = []
    hc = hr = hu = False
    for line in lines:
        s = line.strip()
        if s.startswith("category:"):
            nl.append(f"category: {category_id}"); hc = True
        elif s.startswith("recategorized_at:"):
            nl.append(f"recategorized_at: {now}"); hr = True
        elif s.startswith("updated_at:"):
            nl.append(f"updated_at: {now}"); hu = True
        else:
            nl.append(line)
    if not hc: nl.insert(0, f"category: {category_id}")
    if not hr: nl.append(f"recategorized_at: {now}")
    if not hu: nl.append(f"updated_at: {now}")
    try:
        p.write_text(f"---\n" + "\n".join(nl) + f"\n---{body}")
        return True, None
    except Exception as e:
        return False, f"write: {e}"

def _validated_dest_path(category_id, filename):
    cat = CATEGORIES.get(category_id)
    if not cat:
        raise ValueError("unknown category")
    dd = (Path(VAULT) / cat["path"]).resolve()
    if not str(dd).startswith(str(Path(VAULT).resolve())):
        raise ValueError("escapes vault")
    dd.mkdir(parents=True, exist_ok=True)
    try:
        dd.chmod(0o757)
    except OSError:
        pass
    dp = (dd / filename).resolve()
    if not str(dp).startswith(str(dd)):
        raise ValueError("filename escapes")
    rp = str(dp).replace(str(Path(VAULT).resolve()), "").lstrip("/")
    return dp, rp

def _shape(item):
    dt = datetime.fromtimestamp(item.get("timestamp", 0))
    return {
        "id": item.get("id", ""),
        "title": item.get("title", "Untitled"),
        "channel": item.get("channel", ""),
        "category": item.get("category", ""),
        "path": item.get("path", ""),
        "summary": item.get("summary", ""),
        "date": dt.strftime("%Y-%m-%d %H:%M"),
        "timestamp": item.get("timestamp", 0),
        "honcho_sync_status": item.get("honcho_sync_status", "synced"),
        "recategorized_at": item.get("recategorized_at", None),
        "video_id": item.get("video_id", None),
        "url": item.get("url", ""),
    }

def get_scrapes(limit=50):
    try:
        with open(RECENT_FILE) as f:
            records = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    return [_shape(item) for item in records[:limit]]

_migrate_ids()

# ── Routes ─────────────────────────────────────────────────────

INDEX_HTML = Path("/opt/quarry/index.html").read_text()
@app.route("/")
def index():
    return INDEX_HTML

@app.route("/logo.svg")  # legacy alias — serves the PNG
@app.route("/logo.png")
def logo():
    try:
        return send_file(LOGO_PATH, mimetype="image/png")
    except FileNotFoundError:
        return "", 404

@app.route("/scrape", methods=["POST"])
def scrape():
    """NDJSON stream: {'type':'stage'|'done', ...}. The SPA is the only consumer."""
    data = request.get_json() or {}
    url = data.get("url", "").strip()
    category = data.get("category", "sources").strip()

    def gen():
        if not url:
            yield _ndjson({"type": "done", "ok": False, "error": "URL is required"})
            return
        if category not in CATEGORIES:
            yield _ndjson({"type": "done", "ok": False, "error": "unknown category"})
            return
        video_id = extract_video_id(url)
        if not video_id:
            yield _ndjson({"type": "done", "ok": False, "error": "not a YouTube URL"})
            return
        dup = _preflight_duplicate(url, video_id)
        if dup:
            yield _ndjson({"type": "done", "ok": False, "duplicate": True,
                           "record": _shape(dup)})
            return
        for ev in _run_scraper(url, category):
            if ev["kind"] == "stage":
                yield _ndjson({"type": "stage", "stage": ev["stage"], "message": ev["message"]})
            elif ev["kind"] == "ok":
                rel = ev["file"]
                rec = _record_for_path(rel) or {}
                yield _ndjson({"type": "stage", "stage": "distill", "message": "Distilling knowledge..."})
                dok, dmsg = _distill_note(rel, category)
                if not dok:
                    print(f"[distill] {rel}: {dmsg}", flush=True)
                yield _ndjson({
                    "type": "done", "ok": True, "file": rel,
                    "title": rec.get("title", ""),
                    "channel": rec.get("channel", ""),
                    "video_id": rec.get("video_id", video_id),
                    "summary": rec.get("summary", ""),
                    "category": category,
                })
                return
            else:
                yield _ndjson({"type": "done", "ok": False, "error": ev["error"]})
                return

    return Response(gen(), mimetype="application/x-ndjson")

@app.route("/api/batch-scrape", methods=["POST"])
def batch_scrape():
    """Sequential batch over up to BATCH_MAX_URLS urls, streamed as NDJSON."""
    data = request.get_json() or {}
    urls = data.get("urls") or []
    category = (data.get("category") or "sources").strip()
    if not isinstance(urls, list):
        urls = []
    urls = [str(u).strip() for u in urls if str(u).strip()][:BATCH_MAX_URLS]

    def gen():
        if category not in CATEGORIES:
            yield _ndjson({"type": "batch_done", "error": "unknown category",
                           "summary": {"done": 0, "failed": 0, "duplicate": 0, "invalid": 0}})
            return
        if not urls:
            yield _ndjson({"type": "batch_done", "error": "no urls",
                           "summary": {"done": 0, "failed": 0, "duplicate": 0, "invalid": 0}})
            return
        total = len(urls)
        tally = {"done": 0, "failed": 0, "duplicate": 0, "invalid": 0}
        for i, url in enumerate(urls):
            video_id = extract_video_id(url)
            if not video_id:
                tally["invalid"] += 1
                yield _ndjson({"type": "item", "index": i, "url": url,
                               "status": "invalid", "error": "not a YouTube URL"})
                yield _ndjson({"type": "progress", "done": i + 1, "total": total})
                continue
            dup = _preflight_duplicate(url, video_id)
            if dup:
                tally["duplicate"] += 1
                yield _ndjson({"type": "item", "index": i, "url": url, "status": "duplicate",
                               "title": dup.get("title", ""), "record": _shape(dup)})
                yield _ndjson({"type": "progress", "done": i + 1, "total": total})
                continue
            yield _ndjson({"type": "item", "index": i, "url": url, "status": "processing"})
            title = ""
            finished = False
            for ev in _run_scraper(url, category):
                if ev["kind"] == "stage":
                    msg = ev["message"]
                    if msg.startswith("Title:"):
                        title = msg.split("Title:", 1)[1].strip()
                elif ev["kind"] == "ok":
                    rel = ev["file"]
                    rec = _record_for_path(rel) or {}
                    tally["done"] += 1
                    finished = True
                    yield _ndjson({"type": "item", "index": i, "url": url, "status": "done",
                                   "title": rec.get("title", "") or title, "file": rel})
                    dok, dmsg = _distill_note(rel, category)
                    if not dok:
                        print(f"[distill] {rel}: {dmsg}", flush=True)
                else:
                    tally["failed"] += 1
                    finished = True
                    yield _ndjson({"type": "item", "index": i, "url": url,
                                   "status": "failed", "error": ev["error"]})
            if not finished:
                tally["failed"] += 1
                yield _ndjson({"type": "item", "index": i, "url": url,
                               "status": "failed", "error": "scraper produced no result"})
            yield _ndjson({"type": "progress", "done": i + 1, "total": total})
        yield _ndjson({"type": "batch_done", "summary": tally})

    return Response(gen(), mimetype="application/x-ndjson")

@app.route("/recent")
def recent():
    return jsonify({"scrapes": get_scrapes()})

@app.route("/api/vault")
def api_vault():
    vroot = Path(VAULT).resolve()
    out = []
    for cid, cat in CATEGORIES.items():
        entry = {"id": cid, "label": cat["label"], "path": cat["path"], "count": 0, "files": []}
        try:
            cd = (Path(VAULT) / cat["path"]).resolve()
            if not str(cd).startswith(str(vroot)):
                out.append(entry)
                continue
            found = []
            for fp in cd.glob("*.md"):
                try:
                    mt = fp.stat().st_mtime
                except OSError:
                    mt = 0
                found.append((mt, fp))
            entry["count"] = len(found)
            found.sort(key=lambda t: t[0], reverse=True)
            for mt, fp in found[:100]:
                entry["files"].append({
                    "path": str(fp).replace(str(vroot), "").lstrip("/"),
                    "title": fp.stem,
                    "mtime": datetime.fromtimestamp(mt).astimezone().isoformat() if mt else "",
                })
        except OSError:
            pass
        out.append(entry)
    return jsonify({"categories": out})

@app.route("/view/<path:filepath>")
def view(filepath):
    sp = (Path(VAULT) / filepath).resolve()
    if not str(sp).startswith(str(Path(VAULT).resolve())):
        return "Invalid", 403
    if not sp.exists():
        return "Not found", 404
    return f"<pre>{html.escape(sp.read_text())}</pre>", 200, {"Content-Type": "text/plain; charset=utf-8"}

@app.route("/debug")
def debug():
    info = {
        "vault_path": VAULT,
        "scraper_ok": True,
        "transcript_ok": True,
        "honcho_ok": False,
        "honcho": "?",
        "ytdlp_version": "?",
        "scrape_count": len(_load_records()),
    }
    try:
        r = subprocess.run(
            [YTDLP, "--version"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            info["ytdlp_version"] = r.stdout.strip()
    except Exception:
        pass
    key = os.environ.get("HONCHO_API_KEY", "")
    if key:
        try:
            import urllib.request
            payload = json.dumps({"conclusions": [{"content": "quarry health check", "observer_id": "hermes", "observed_id": "ishmael"}]}).encode()
            req = urllib.request.Request(
                HONCHO_URL, data=payload,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                info["honcho"] = f"HTTP {resp.status}"
                info["honcho_ok"] = resp.status in (200, 201)
        except Exception as e:
            info["honcho"] = str(e)[:40]
    return jsonify(info)

def _honcho_probe(timeout=3):
    key = os.environ.get("HONCHO_API_KEY", "")
    if not key:
        return False, "no honcho key"
    try:
        import urllib.request
        payload = json.dumps({"conclusions": [{"content": "quarry health check", "observer_id": "hermes", "observed_id": "ishmael"}]}).encode()
        req = urllib.request.Request(
            HONCHO_URL, data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status in (200, 201), f"HTTP {resp.status}"
    except Exception as e:
        return False, str(e)[:80]

def _ytdlp_version():
    try:
        r = subprocess.run([YTDLP, "--version"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return ""

@app.route("/api/health")
def api_health():
    vp = Path(VAULT)
    if not vp.exists():
        obsidian = {"ok": False, "detail": f"{VAULT} does not exist"}
    elif not vp.is_dir():
        obsidian = {"ok": False, "detail": f"{VAULT} is not a directory"}
    elif not os.access(VAULT, os.W_OK):
        obsidian = {"ok": False, "detail": f"{VAULT} is not writable"}
    else:
        obsidian = {"ok": True, "detail": VAULT}

    hok, hdetail = _honcho_probe()
    hermes = {"ok": hok, "detail": hdetail}

    sp = Path(SCRAPER)
    if not sp.exists():
        worker = {"ok": False, "detail": f"{SCRAPER} not found"}
    elif not os.access(SCRAPER, os.X_OK):
        worker = {"ok": False, "detail": f"{SCRAPER} is not executable"}
    else:
        ver = _ytdlp_version()
        detail = SCRAPER + (f" · yt-dlp {ver}" if ver else "")
        worker = {"ok": True, "detail": detail}

    return jsonify({"obsidian": obsidian, "hermes": hermes, "worker": worker,
                    "version": HEALTH_VERSION})

@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    settings = _load_settings()
    if request.method == "GET":
        return jsonify(settings)
    data = request.get_json() or {}
    if "default_category" in data:
        dc = str(data.get("default_category") or "").strip()
        if dc not in CATEGORIES:
            return jsonify({"error": "unknown category"}), 400
        settings["default_category"] = dc
    if "hermes_webui_url" in data:
        hu = str(data.get("hermes_webui_url") or "").strip()
        if not hu.startswith("http"):
            return jsonify({"error": "hermes_webui_url must start with http"}), 400
        settings["hermes_webui_url"] = hu
    try:
        _write_json_atomic(SETTINGS_FILE, settings)
    except Exception as e:
        return jsonify({"error": f"write failed: {e}"}), 500
    return jsonify(settings)

@app.route("/api/check")
@app.route("/api/suggest")  # alias — /api/check is the canonical name
def api_check():
    """Paste-time probe: is this a video we already have, and where does it belong?"""
    url = (request.args.get("url") or "").strip()
    video_id = extract_video_id(url)
    if not video_id:
        return jsonify({"valid": False, "video_id": None})
    records = _load_records()
    dup = _find_by_video_id(records, video_id)
    if dup:
        return jsonify({"valid": True, "video_id": video_id, "duplicate": True,
                        "record": _shape(dup)})
    meta = _ytdlp_meta(url, video_id)
    title = meta.get("title", "")
    channel = meta.get("channel", "")
    dup = _find_by_title_slug(records, title)
    if dup:
        return jsonify({"valid": True, "video_id": video_id, "duplicate": True,
                        "record": _shape(dup)})
    return jsonify({"valid": True, "video_id": video_id, "duplicate": False,
                    "suggested_category": _suggest_category(records, channel),
                    "title": title, "channel": channel})

@app.route("/delete-scrape", methods=["POST"])
def delete_scrape():
    data = request.get_json() or {}
    did = data.get("id", "").strip()
    if not did:
        return jsonify({"ok": False, "error": "id required"}), 400
    records = _load_records()
    n = len(records)
    records = [r for r in records if r.get("id") != did]
    if len(records) == n:
        return jsonify({"ok": False, "error": "not found"}), 404
    _write_records_atomic(records)
    return jsonify({"ok": True, "removed": n - len(records)})

@app.route("/api/items/<item_id>/recategorize", methods=["POST"])
def recategorize(item_id):
    data = request.get_json() or {}
    nc = data.get("category", "").strip()
    if not nc:
        return jsonify({"success": False, "error": "category required"}), 400
    if nc not in CATEGORIES:
        return jsonify({"success": False, "error": "unknown category"}), 400
    records = _load_records()
    item = _find_record(records, item_id)
    if not item:
        return jsonify({"success": False, "error": "not found"}), 404
    oc = item.get("category", "sources")
    if nc == oc:
        return jsonify({"success": True, "info": "already in this category"})
    oldp = item.get("path", "")
    if not oldp:
        return jsonify({"success": False, "error": "no path"}), 400
    ofp = (Path(VAULT) / oldp).resolve()
    if not ofp.exists():
        return jsonify({"success": False, "error": "source not found"}), 404
    fn = ofp.name
    try:
        dfp, dr = _validated_dest_path(nc, fn)
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    if dfp.exists():
        try:
            if ofp.read_text() == dfp.read_text():
                item["category"] = nc
                item["path"] = dr
                item["honcho_sync_status"] = "pending"
                _write_records_atomic(records)
                return jsonify({"success": True, "info": "same content, record updated"})
        except Exception:
            pass
        base = dfp.stem
        sfx = dfp.suffix
        c = 2
        while dfp.exists():
            dfp = dfp.with_name(f"{base}-{c}{sfx}")
            c += 1
        dr = str(dfp).replace(str(Path(VAULT).resolve()), "").lstrip("/")
    try:
        with open(str(ofp), "rb") as sf:
            data_b = sf.read()
        with open(str(dfp), "wb") as df:
            df.write(data_b)
    except Exception as e:
        return jsonify({"success": False, "error": f"file: {e}"}), 500
    fm_ok, fm_err = _update_note_frontmatter(str(dfp), nc)
    if not fm_ok:
        if dfp.exists():
            with open(str(ofp), "wb") as sf:
                sf.write(data_b)
            dfp.unlink(missing_ok=True)
        return jsonify({"success": False, "error": f"frontmatter: {fm_err}"}), 500
    ofp.unlink(missing_ok=True)
    item["category"] = nc
    item["path"] = dr
    item["updated_at"] = datetime.now().astimezone().isoformat()
    item["recategorized_at"] = datetime.now().astimezone().isoformat()
    _write_records_atomic(records)
    hok, herr = _update_honcho(item, nc)
    item["honcho_sync_status"] = "synced" if hok else "pending"
    if herr:
        item["honcho_sync_error"] = herr
    _write_records_atomic(records)
    return jsonify({"success": True, "item_id": item_id, "old_category": oc, "new_category": nc})

@app.route("/api/items/<item_id>/honcho-sync", methods=["POST"])
def honcho_sync(item_id):
    records = _load_records()
    item = _find_record(records, item_id)
    if not item:
        return jsonify({"success": False, "error": "not found"}), 404
    cat = item.get("category", "sources")
    ok, err = _update_honcho(item, cat)
    if ok:
        item["honcho_sync_status"] = "synced"
        item["honcho_sync_error"] = None
        _write_records_atomic(records)
        return jsonify({"success": True, "honcho_sync_status": "synced"})
    else:
        item["honcho_sync_status"] = "failed"
        item["honcho_sync_error"] = err
        _write_records_atomic(records)
        return jsonify({"success": False, "honcho_sync_status": "failed", "error": err})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
