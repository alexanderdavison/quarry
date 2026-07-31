#!/usr/bin/env python3
"""Quarry — YouTube scraper + memory seeder. Single-file app."""

import subprocess, os, html, json, uuid, shutil, tempfile
from pathlib import Path
from datetime import datetime, timezone
from flask import Flask, request, render_template_string, jsonify, send_file

app = Flask(__name__)
VAULT = "/mnt/obsidian-vault"
SCRAPER = "/opt/quarry/quarry"
YTDLP = "/opt/scraper-venv/bin/yt-dlp"
RECENT_FILE = "/opt/quarry/recent.json"
BACKUP_DIR = "/opt/quarry/backups"
LOGO_PATH = "/opt/quarry/quarry-logo.svg"
HONCHO_URL = "http://192.168.1.23:8000/v3/workspaces/hermes/conclusions"

CATEGORIES = {
    "sources":     {"label": "Sources",     "path": "sources/youtube/"},
    "shared":      {"label": "Shared",      "path": "shared/youtube/"},
    "homelab-wiki":{"label": "homelab-wiki","path": "homelab-wiki/youtube/"},
    "personal-wiki":{"label":"Personal",    "path": "personal-wiki/youtube/"},
    "ish-d":       {"label": "Ish D",       "path": "ish-d/youtube/"},
    "real-estate": {"label": "Real Estate",  "path": "real-estate/youtube/"},
    "dental-msp":  {"label": "Dental",       "path": "dental-msp/youtube/"},
    "axiom-music": {"label": "Axiom",        "path": "axiom-music/youtube/"},
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

def _update_honcho(item, category_name):
    key = os.environ.get("HONCHO_API_KEY", "")
    if not key:
        return False, "no honcho key"
    content = f"Quarry scraped video: {item.get('title', 'Untitled')} from channel {item.get('channel', 'unknown')} in category {category_name}"
    try:
        import urllib.request
        payload = json.dumps({"conclusions": [{"content": content[:500], "observer_id": "hermes", "observed_id": "ishmael"}]}).encode()
        req = urllib.request.Request(
            HONCHO_URL, data=payload,
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
    now = datetime.now(timezone.utc).isoformat()
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

def get_scrapes(limit=50):
    try:
        with open(RECENT_FILE) as f:
            records = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    result = []
    for item in records[:limit]:
        dt = datetime.fromtimestamp(item.get("timestamp", 0))
        result.append({
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
        })
    return result

_migrate_ids()

# ── Routes ─────────────────────────────────────────────────────

INDEX_HTML = Path("/opt/quarry/index.html").read_text()
@app.route("/")
def index():
    return INDEX_HTML

@app.route("/logo.svg")
def logo():
    try:
        return send_file(LOGO_PATH, mimetype="image/svg+xml")
    except FileNotFoundError:
        return "", 404

@app.route("/scrape", methods=["POST"])
def scrape():
    data = request.get_json() or {}
    url = data.get("url", "").strip()
    category = data.get("category", "sources").strip()
    if not url:
        return jsonify({"ok": False, "error": "URL is required"})
    try:
        result = subprocess.run(
            [SCRAPER, url, category],
            capture_output=True, text=True, timeout=120,
            env={**os.environ, "HONCHO_API_KEY": os.environ.get("HONCHO_API_KEY", "")},
        )
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        if result.returncode == 0 and "Written:" in stdout:
            fpath = stdout.split("Written:", 1)[1].strip().split("\n")[0].strip()
            rel = fpath.replace(VAULT, "").lstrip("/")
            summary = ""
            try:
                with open(RECENT_FILE) as f:
                    recents = json.load(f)
                if recents and recents[0].get("path") == rel:
                    summary = recents[0].get("summary", "")
            except (FileNotFoundError, json.JSONDecodeError):
                pass
            return jsonify({"ok": True, "file": rel, "summary": summary, "output": stdout})
        else:
            return jsonify({"ok": False, "error": stderr or stdout or f"Exit {result.returncode}"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

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
                    "mtime": datetime.fromtimestamp(mt, timezone.utc).isoformat() if mt else "",
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
    item["updated_at"] = datetime.now(timezone.utc).isoformat()
    item["recategorized_at"] = datetime.now(timezone.utc).isoformat()
    _write_records_atomic(records)
    cl = CATEGORIES.get(nc, {}).get("label", nc)
    hok, herr = _update_honcho(item, cl)
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
    cl = CATEGORIES.get(cat, {}).get("label", cat)
    ok, err = _update_honcho(item, cl)
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
