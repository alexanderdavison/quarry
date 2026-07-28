#!/usr/bin/env python3
"""quarry WebUI — Scrape YouTube into Obsidian + seed Honcho memory"""

import html, json, os, subprocess
from pathlib import Path
from datetime import datetime
from flask import Flask, request, render_template_string, jsonify

app = Flask(__name__)
VAULT = "/mnt/obsidian-vault"
RECENT_FILE = "/opt/quarry/recent.json"
SCRAPER = "/opt/quarry/quarry"

INDEX_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Quarry</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, sans-serif;
    background: #0d0d0d; color: #c0c0c0;
    min-height: 100vh; display: flex; flex-direction: column;
  }
  a { color: inherit; text-decoration: none; }

  /* ── top bar ── */
  .topbar {
    display: flex; align-items: center; justify-content: space-between;
    padding: 14px 24px; border-bottom: 1px solid #1a1a1a;
  }
  .topbar .brand {
    font-size: 1.25rem; font-weight: 600; color: #e0e0e0;
    letter-spacing: -0.02em;
  }
  .topbar .brand span { color: #666; font-weight: 400; }
  .topbar .nav { display: flex; gap: 4px; }
  .topbar .nav a {
    font-size: 0.8rem; color: #555; padding: 6px 12px;
    border-radius: 6px; transition: all 0.15s;
  }
  .topbar .nav a:hover { color: #aaa; background: #141414; }

  /* ── main ── */
  .main {
    flex: 1; display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    padding: 40px 20px 60px;
  }
  .main-inner { width: 100%; max-width: 520px; }

  /* ── icon ── */
  .icon-row { text-align: center; margin-bottom: 28px; }
  .icon-row svg { width: 40px; height: 40px; }
  .icon-row .brand-text {
    font-size: 1.6rem; font-weight: 700; color: #e0e0e0;
    letter-spacing: -0.03em; margin-top: 6px;
  }

  /* ── input ── */
  .input-wrap {
    display: flex; align-items: center; gap: 0;
    background: #181818; border: 1px solid #282828;
    border-radius: 100px; padding: 4px;
    transition: border-color 0.2s;
  }
  .input-wrap:focus-within { border-color: #444; }
  .input-wrap input {
    flex: 1; background: transparent; border: none;
    color: #e0e0e0; font-size: 0.95rem; padding: 12px 18px;
    outline: none; font-family: inherit;
  }
  .input-wrap input::placeholder { color: #444; }
  .input-wrap button {
    background: #2a2a2a; color: #ccc; border: none;
    border-radius: 100px; padding: 10px 22px;
    font-size: 0.85rem; font-weight: 500; cursor: pointer;
    transition: all 0.15s; white-space: nowrap; font-family: inherit;
    margin: 2px;
  }
  .input-wrap button:hover { background: #333; color: #e0e0e0; }
  .input-wrap button:disabled { opacity: 0.3; cursor: not-allowed; }

  /* ── category pills ── */
  .pills {
    display: flex; flex-wrap: wrap; gap: 5px;
    margin-top: 16px; justify-content: center;
  }
  .pill {
    padding: 5px 14px; border-radius: 100px;
    font-size: 0.75rem; cursor: pointer; position: relative;
    background: #181818; color: #555; border: 1px solid #242424;
    transition: all 0.15s; user-select: none;
  }
  .pill:hover { border-color: #333; color: #888; }
  .pill.active { background: #1e1e1e; color: #d0d0d0; border-color: #3a3a3a; }
  .pill .path-hint {
    display: none; position: absolute; top: calc(100% + 6px); left: 50%;
    transform: translateX(-50%); background: #181818; border: 1px solid #2a2a2a;
    border-radius: 6px; padding: 4px 10px; font-size: 0.65rem;
    color: #666; white-space: nowrap; z-index: 10;
  }
  .pill:hover .path-hint { display: block; }

  /* ── result ── */
  .result {
    margin-top: 24px; display: none;
    text-align: center; font-size: 0.85rem;
  }
  .result.show { display: block; }
  .result.success .file-path {
    font-size: 0.75rem; color: #58a6ff; font-family: "SF Mono","Fira Code",monospace;
    word-break: break-all; margin-bottom: 4px;
  }
  .result.success .summary {
    font-size: 0.8rem; color: #666; line-height: 1.5;
    margin-bottom: 12px;
  }
  .result.success .view-btn {
    display: inline-block; padding: 8px 24px;
    background: #1e1e1e; border: 1px solid #2a2a2a; border-radius: 100px;
    color: #aaa; font-size: 0.8rem; transition: all 0.15s;
  }
  .result.success .view-btn:hover { border-color: #444; color: #e0e0e0; background: #222; }
  .result.error { color: #f77; }
  .result.loading { color: #666; }
  .spinner {
    display: inline-block; width: 16px; height: 16px;
    border: 2px solid #282828; border-top-color: #888;
    border-radius: 50%; animation: spin 0.6s linear infinite;
    vertical-align: middle; margin-right: 8px;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* ── recent ── */
  .recent { margin-top: 48px; }
  .recent-header {
    display: flex; align-items: center; gap: 8px;
    font-size: 0.7rem; color: #3a3a3a; text-transform: uppercase;
    letter-spacing: 0.08em; margin-bottom: 12px;
  }
  .recent-header::after {
    content: ""; flex: 1; height: 1px; background: #1a1a1a;
  }
  .recent-item {
    padding: 10px 0; border-bottom: 1px solid #121212;
    display: flex; justify-content: space-between; align-items: flex-start; gap: 12px;
  }
  .recent-item:last-child { border-bottom: none; }
  .recent-item .right { text-align: right; flex-shrink: 0; }
  .recent-item .title {
    font-size: 0.85rem; color: #bbb; line-height: 1.3;
    display: -webkit-box; -webkit-line-clamp: 1; -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .recent-item .title a { color: #bbb; }
  .recent-item .title a:hover { color: #e0e0e0; }
  .recent-item .summary {
    font-size: 0.72rem; color: #555; margin-top: 2px;
    display: -webkit-box; -webkit-line-clamp: 1; -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .recent-item .meta {
    font-size: 0.62rem; color: #3a3a3a; margin-top: 4px;
  }
  .recent-item .tag {
    font-size: 0.6rem; color: #444; background: #0f0f0f;
    padding: 2px 8px; border-radius: 100px;
  }
  .recent-empty { text-align: center; color: #2a2a2a; font-size: 0.8rem; padding: 2rem 0; }

  /* ── footer ── */
  .footer {
    text-align: center; padding: 16px; font-size: 0.65rem; color: #2a2a2a;
  }
  .footer a { color: #333; }
  .footer a:hover { color: #555; }

  /* ── settings panel ── */
  .panel {
    display: none; position: fixed; inset: 0; z-index: 100;
    background: rgba(0,0,0,0.5); backdrop-filter: blur(6px);
    align-items: center; justify-content: center;
  }
  .panel.open { display: flex; }
  .panel-inner {
    background: #121212; border: 1px solid #242424; border-radius: 16px;
    width: 100%; max-width: 420px; max-height: 70vh; overflow-y: auto;
    padding: 24px; position: relative;
  }
  .panel-inner .close {
    position: absolute; top: 12px; right: 14px;
    background: none; border: none; color: #444; font-size: 1.2rem;
    cursor: pointer; padding: 4px 8px; border-radius: 6px; line-height: 1;
  }
  .panel-inner .close:hover { color: #aaa; background: #1a1a1a; }
  .panel-inner h2 {
    font-size: 0.85rem; font-weight: 500; color: #888;
    margin-bottom: 16px; letter-spacing: 0.03em;
  }
  .setting-row {
    display: flex; justify-content: space-between; align-items: center;
    padding: 10px 0; border-bottom: 1px solid #1a1a1a;
  }
  .setting-row:last-child { border-bottom: none; }
  .setting-row .label { font-size: 0.85rem; color: #bbb; }
  .setting-row .desc { font-size: 0.7rem; color: #444; margin-top: 2px; }
  .toggle {
    position: relative; width: 36px; height: 20px; flex-shrink: 0;
    background: #242424; border-radius: 10px; cursor: pointer;
    transition: background 0.2s; border: none; padding: 0;
  }
  .toggle.on { background: #444; }
  .toggle::after {
    content: ""; position: absolute; top: 2px; left: 2px;
    width: 16px; height: 16px; border-radius: 50%;
    background: #555; transition: all 0.2s;
  }
  .toggle.on::after { left: 18px; background: #ccc; }

  .debug-row {
    display: flex; justify-content: space-between; padding: 5px 0;
    font-size: 0.75rem; border-bottom: 1px solid #121212;
  }
  .debug-row:last-child { border-bottom: none; }
  .debug-row .key { color: #444; }
  .debug-row .val { color: #888; font-family: "SF Mono","Fira Code",monospace; font-size: 0.7rem; }
  .debug-row .val.good { color: #5a5; }
  .debug-row .val.warn { color: #c93; }

  .test-btn {
    margin-top: 12px; width: 100%; padding: 8px;
    background: #181818; border: 1px solid #242424; border-radius: 8px;
    color: #666; font-size: 0.75rem; cursor: pointer; font-family: inherit;
    transition: all 0.15s;
  }
  .test-btn:hover { border-color: #3a3a3a; color: #aaa; }

  @media (max-width: 480px) {
    .main { padding: 20px 16px 40px; }
    .topbar { padding: 10px 16px; }
    .topbar .nav a { font-size: 0.7rem; padding: 4px 8px; }
    .pills { gap: 4px; }
    .pill { font-size: 0.7rem; padding: 4px 10px; }
    .recent-item { flex-direction: column; gap: 4px; }
    .recent-item .right { text-align: left; }
  }
</style>
</head>
<body>

<div class="topbar">
  <div class="brand">Quarry <span>β</span></div>
  <div class="nav">
    <a href="#" onclick="event.preventDefault();openSettings()">settings</a>
    <a href="https://192.168.1.19:3000/ishmael/quarry" target="_blank">source</a>
  </div>
</div>

<div class="main">
  <div class="main-inner">
    <div class="icon-row">
      <svg viewBox="0 0 40 40" fill="none">
        <rect x="3" y="10" width="34" height="22" rx="4" stroke="#444" stroke-width="1.5" fill="none"/>
        <polygon points="16,14 16,28 28,21" fill="#666"/>
      </svg>
      <div class="brand-text">Quarry</div>
    </div>

    <form id="scrape-form">
      <div class="input-wrap">
        <input type="url" id="url-input" placeholder="Paste a YouTube URL" required autofocus>
        <button type="submit" id="submit-btn">scrape</button>
      </div>
      <div class="pills" id="pills">
        <span class="pill active" data-v="sources">sources<span class="path-hint">vault/sources/youtube/</span></span>
        <span class="pill" data-v="shared">shared<span class="path-hint">vault/shared/youtube/</span></span>
        <span class="pill" data-v="homelab-wiki">wiki<span class="path-hint">vault/homelab-wiki/youtube/</span></span>
        <span class="pill" data-v="personal-wiki">personal<span class="path-hint">vault/personal-wiki/youtube/</span></span>
        <span class="pill" data-v="real-estate">real-estate<span class="path-hint">vault/real-estate/youtube/</span></span>
        <span class="pill" data-v="dental-msp">dental<span class="path-hint">vault/dental-msp/youtube/</span></span>
        <span class="pill" data-v="axiom-music">music<span class="path-hint">vault/axiom-music/youtube/</span></span>
      </div>
    </form>

    <div id="result" class="result"></div>

    <div class="recent" id="recent-section">
      <div class="recent-header">recent</div>
      <div id="recent-list"></div>
    </div>
  </div>
</div>

<div class="footer">
  <a href="#" onclick="event.preventDefault();openSettings()">settings</a>
  &nbsp;·&nbsp; scrapes to vault
</div>

<!-- settings panel -->
<div class="panel" id="settings-panel">
  <div class="panel-inner" onclick="event.stopPropagation()">
    <button class="close" onclick="closeSettings()">&#x2715;</button>
    <h2>settings</h2>

    <div class="setting-row">
      <div>
        <div class="label">Transcript</div>
        <div class="desc">Include transcript in notes</div>
      </div>
      <button class="toggle on" id="toggle-transcript" onclick="this.classList.toggle('on')"></button>
    </div>
    <div class="setting-row">
      <div>
        <div class="label">Description</div>
        <div class="desc">Include video description</div>
      </div>
      <button class="toggle on" id="toggle-desc" onclick="this.classList.toggle('on')"></button>
    </div>

    <div style="margin-top:16px;padding-top:12px;border-top:1px solid #1a1a1a">
      <div class="debug-row"><span class="key">scraper</span><span class="val" id="debug-scraper">...</span></div>
      <div class="debug-row"><span class="key">yt-dlp</span><span class="val" id="debug-ytdlp">...</span></div>
      <div class="debug-row"><span class="key">transcript api</span><span class="val" id="debug-transcript">...</span></div>
      <div class="debug-row"><span class="key">honcho</span><span class="val" id="debug-honcho">...</span></div>
      <div class="debug-row"><span class="key">videos scraped</span><span class="val" id="debug-count">...</span></div>
    </div>

    <button class="test-btn" id="test-btn" onclick="runTest()">test scrape</button>
    <div class="test-result" id="test-result" style="margin-top:6px;font-size:0.7rem;color:#555"></div>
  </div>
</div>

<script>
  const pills = document.querySelectorAll('.pill');
  let selectedCategory = 'sources';
  pills.forEach(p => {
    p.addEventListener('click', () => {
      pills.forEach(x => x.classList.remove('active'));
      p.classList.add('active');
      selectedCategory = p.dataset.v;
    });
  });

  const form = document.getElementById('scrape-form');
  const input = document.getElementById('url-input');
  const btn = document.getElementById('submit-btn');
  const result = document.getElementById('result');
  const recent = document.getElementById('recent-list');

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const url = input.value.trim();
    if (!url) return;

    btn.disabled = true;
    result.className = 'result show loading';
    result.innerHTML = '<span class="spinner"></span> scraping...';

    const inclTranscript = document.getElementById('toggle-transcript').classList.contains('on');
    const inclDesc = document.getElementById('toggle-desc').classList.contains('on');

    try {
      const r = await fetch('/scrape', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url, category: selectedCategory, transcript: inclTranscript, description: inclDesc })
      });
      const d = await r.json();
      if (d.ok) {
        result.className = 'result show success';
        let html = '<div class="file-path">' + esc(d.file) + '</div>';
        if (d.summary) html += '<div class="summary">' + esc(d.summary) + '</div>';
        html += '<a href="/view/' + encodeURIComponent(d.file) + '" target="_blank" class="view-btn">view note</a>';
        result.innerHTML = html;
        loadRecent();
      } else {
        result.className = 'result show error';
        result.innerHTML = '&#x2717; ' + esc(d.error);
      }
    } catch (err) {
      result.className = 'result show error';
      result.innerHTML = '&#x2717; ' + esc(err.message);
    }
    btn.disabled = false;
    input.value = '';
    input.focus();
  });

  function esc(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  function openSettings() {
    document.getElementById('settings-panel').classList.add('open');
    document.body.style.overflow = 'hidden';
    loadDebugInfo();
  }
  function closeSettings() {
    document.getElementById('settings-panel').classList.remove('open');
    document.body.style.overflow = '';
  }
  document.getElementById('settings-panel').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) closeSettings();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeSettings();
  });

  async function loadDebugInfo() {
    try {
      const r = await fetch('/debug');
      const d = await r.json();
      document.getElementById('debug-scraper').textContent = d.scraper || 'ok';
      document.getElementById('debug-scraper').className = d.scraper_ok ? 'val good' : 'val warn';
      document.getElementById('debug-ytdlp').textContent = d.ytdlp_version || '?';
      document.getElementById('debug-transcript').textContent = d.transcript_api || '?';
      document.getElementById('debug-transcript').className = d.transcript_ok ? 'val good' : 'val warn';
      document.getElementById('debug-honcho').textContent = d.honcho || '?';
      document.getElementById('debug-honcho').className = d.honcho_ok ? 'val good' : 'val warn';
      document.getElementById('debug-count').textContent = d.scrape_count + ' videos';
    } catch {}
  }

  async function runTest() {
    const tb = document.getElementById('test-btn');
    const tr = document.getElementById('test-result');
    tb.disabled = true;
    tr.textContent = 'running...';
    try {
      const r = await fetch('/test-scrape', { method: 'POST' });
      const d = await r.json();
      tr.textContent = d.ok ? '✓ ' + (d.file || 'OK') : '✗ ' + (d.error || 'failed');
      if (d.ok) loadRecent();
    } catch (err) {
      tr.textContent = '✗ ' + err.message;
    }
    tb.disabled = false;
  }

  async function loadRecent() {
    try {
      const r = await fetch('/recent');
      const d = await r.json();
      if (d.scrapes && d.scrapes.length > 0) {
        recent.innerHTML = d.scrapes.map(f =>
          '<div class="recent-item">'
          + '<div>'
          + '<div class="title"><a href="/view/' + encodeURIComponent(f.path) + '" target="_blank">' + esc(f.title) + '</a></div>'
          + '<div class="summary">' + esc(f.summary) + '</div>'
          + '<div class="meta">' + esc(f.date) + '</div>'
          + '</div>'
          + '<div class="right"><span class="tag">' + esc(f.category) + '</span></div>'
          + '</div>'
        ).join('');
      } else {
        recent.innerHTML = '<div class="recent-empty">no scrapes yet</div>';
      }
    } catch {}
  }
  loadRecent();
</script>
</body>
</html>
"""
@app.route("/")
def index():
    return render_template_string(INDEX_HTML)


@app.route("/scrape", methods=["POST"])
def scrape():
    data = request.get_json()
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
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()

        if result.returncode == 0 and "Written:" in stdout:
            file_path = stdout.split("Written:", 1)[1].strip()
            rel_path = file_path.replace(VAULT, "").lstrip("/")
            # Pull summary from recent.json if available
            summary = ""
            try:
                with open(RECENT_FILE) as f:
                    recents = json.load(f)
                if recents and recents[0].get("path") == rel_path:
                    summary = recents[0].get("summary", "")
            except (FileNotFoundError, json.JSONDecodeError):
                pass
            return jsonify({"ok": True, "file": rel_path, "summary": summary, "output": stdout})
        else:
            err = stderr or stdout or f"Exit code: {result.returncode}"
            return jsonify({"ok": False, "error": err})
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "Scrape timed out after 120s"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/recent")
def recent():
    """Return recent scrapes from recent.json"""
    scrapes = []
    try:
        with open(RECENT_FILE) as f:
            data = json.load(f)
        for item in data[:10]:
            dt = datetime.fromtimestamp(item.get("timestamp", 0))
            scrapes.append({
                "title": item.get("title", "Untitled"),
                "channel": item.get("channel", ""),
                "category": item.get("category", ""),
                "path": item.get("path", ""),
                "summary": item.get("summary", ""),
                "date": dt.strftime("%Y-%m-%d %H:%M"),
            })
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return jsonify({"scrapes": scrapes})


@app.route("/view/<path:filepath>")
def view(filepath):
    safe_path = (Path(VAULT) / filepath).resolve()
    if not str(safe_path).startswith(VAULT):
        return "Invalid path", 403
    if not safe_path.exists():
        return "Not found", 404
    content = safe_path.read_text()
    return f"<pre>{html.escape(content)}</pre>", 200, {"Content-Type": "text/plain; charset=utf-8"}


@app.route("/debug")
def debug():
    info = {
        "vault_path": VAULT,
        "scraper": "ok",
        "scraper_ok": True,
        "transcript_api": "?",
        "transcript_ok": False,
        "ytdlp_version": "?",
        "honcho": "?",
        "honcho_ok": False,
        "scrape_count": 0,
    }
    try:
        r = subprocess.run(
            [f"{Path(SCRAPER).parent}/scraper-venv/bin/yt-dlp", "--version"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            info["ytdlp_version"] = r.stdout.strip()
    except Exception:
        pass
    try:
        r = subprocess.run(
            ["/opt/scraper-venv/bin/python3", "-c",
             "from youtube_transcript_api import YouTubeTranscriptApi; print('ok')"],
            capture_output=True, text=True, timeout=5,
        )
        info["transcript_api"] = "available" if r.returncode == 0 else "unavailable"
        info["transcript_ok"] = r.returncode == 0
    except Exception:
        info["transcript_api"] = "error"
    # Check Honcho connectivity
    honcho_key = os.environ.get("HONCHO_API_KEY", "")
    if honcho_key:
        try:
            import urllib.request
            req = urllib.request.Request(
                "http://192.168.1.23:8000/v3/workspaces/hermes/conclude",
                data=b'{"peer":"ishmael","conclusion":"quarry health check"}',
                headers={"Content-Type": "application/json", "X-API-Key": honcho_key},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                info["honcho"] = f"HTTP {resp.status}"
                info["honcho_ok"] = resp.status in (200, 201)
        except Exception as e:
            info["honcho"] = str(e)[:40]
    else:
        info["honcho"] = "no key"
    # Count scrapes
    try:
        with open(RECENT_FILE) as f:
            info["scrape_count"] = len(json.load(f))
    except Exception:
        info["scrape_count"] = 0
    return jsonify(info)


@app.route("/test-scrape", methods=["POST"])
def test_scrape():
    try:
        result = subprocess.run(
            [SCRAPER, "https://www.youtube.com/watch?v=jNQXAC9IVRw", "sources"],
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "HONCHO_API_KEY": os.environ.get("HONCHO_API_KEY", "")},
        )
        stdout = result.stdout.strip() or result.stderr.strip()
        if result.returncode == 0 and "Written:" in stdout:
            fpath = stdout.split("Written:", 1)[1].strip()
            rel = fpath.replace(VAULT, "").lstrip("/")
            return jsonify({"ok": True, "file": rel, "output": stdout})
        else:
            return jsonify({"ok": False, "error": stdout or f"exit {result.returncode}"})
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "timed out"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)