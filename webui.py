#!/usr/bin/env python3
"""yt-to-obi WebUI — MeTube-style interface for scraping YouTube into Obsidian"""

import subprocess, os, html, json
from pathlib import Path
from flask import Flask, request, render_template_string, jsonify

app = Flask(__name__)
VAULT = "/mnt/obsidian-vault"

INDEX_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>yt → obi</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #0a0a0a; color: #e0e0e0;
    min-height: 100vh;
  }

  /* ── layout ── */
  .page { max-width: 520px; margin: 0 auto; padding: 2rem 1rem; }
  .header {
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 2rem; padding-top: 4vh;
  }
  .header .brand { display: flex; align-items: center; gap: 10px; }
  .header .brand svg { width: 32px; height: 32px; }
  .header .brand span { font-size: 1rem; font-weight: 500; color: #888; }
  .header .gear {
    background: none; border: none; color: #333; font-size: 1.3rem;
    cursor: pointer; padding: 6px; border-radius: 8px; line-height: 1;
    transition: all 0.15s;
  }
  .header .gear:hover { color: #888; background: #141414; }

  /* ── input ── */
  .input-row {
    display: flex; gap: 8px;
    background: #141414; border: 1px solid #2a2a2a;
    border-radius: 14px; padding: 6px;
    transition: border-color 0.2s;
  }
  .input-row:focus-within { border-color: #555; }
  .input-row input {
    flex: 1; background: transparent; border: none;
    color: #e0e0e0; font-size: 1rem; padding: 10px 14px;
    outline: none; font-family: inherit;
  }
  .input-row input::placeholder { color: #444; }
  .input-row button {
    background: #e0e0e0; color: #0a0a0a; border: none;
    border-radius: 10px; padding: 10px 20px;
    font-size: 0.9rem; font-weight: 600; cursor: pointer;
    transition: opacity 0.15s; white-space: nowrap; font-family: inherit;
  }
  .input-row button:hover { opacity: 0.8; }
  .input-row button:disabled { opacity: 0.35; cursor: not-allowed; }

  /* ── pills ── */
  .pills {
    display: flex; flex-wrap: wrap; gap: 6px;
    margin-top: 12px; justify-content: center;
  }
  .pill {
    padding: 4px 14px; border-radius: 20px;
    font-size: 0.75rem; cursor: pointer;
    background: #141414; color: #555; border: 1px solid #2a2a2a;
    transition: all 0.15s; user-select: none;
  }
  .pill:hover { border-color: #3a3a3a; color: #888; }
  .pill.active { background: #1c1c1c; color: #e0e0e0; border-color: #3a3a3a; }

  /* ── result ── */
  .result {
    margin-top: 1.5rem; border-radius: 12px;
    background: #141414; border: 1px solid #2a2a2a;
    padding: 1rem; display: none;
    font-size: 0.85rem; line-height: 1.5;
  }
  .result.success { display: block; border-color: #2a2a2a; }
  .result.error { display: block; border-color: #4a2020; color: #f88; }
  .result.loading { display: block; text-align: center; color: #888; }
  .result a { color: #58a6ff; text-decoration: none; }
  .result .spinner {
    display: inline-block; width: 18px; height: 18px;
    border: 2px solid #333; border-top-color: #fff;
    border-radius: 50%; animation: spin 0.6s linear infinite;
    vertical-align: middle; margin-right: 8px;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .result .path { color: #58a6ff; word-break: break-all; font-family: "SF Mono","Fira Code",monospace; font-size: 0.8rem; }
  .result .view-link {
    display: inline-block; margin-top: 10px;
    padding: 6px 16px; background: #1c1c1c; border-radius: 8px;
    font-size: 0.8rem; color: #aaa; border: 1px solid #2a2a2a; text-decoration: none;
    transition: all 0.15s;
  }
  .result .view-link:hover { background: #222; border-color: #444; color: #e0e0e0; }

  /* ── recent ── */
  .recent { margin-top: 3rem; }
  .recent-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem; }
  .recent-header h2 { font-size: 0.7rem; font-weight: 500; color: #444; text-transform: uppercase; letter-spacing: 0.08em; }
  .recent-item {
    display: flex; justify-content: space-between; align-items: center;
    padding: 10px 0; border-bottom: 1px solid #111;
  }
  .recent-item:last-child { border-bottom: none; }
  .recent-item .info { flex: 1; min-width: 0; }
  .recent-item .title {
    font-size: 0.85rem; color: #ccc;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .recent-item .title a { color: #ccc; text-decoration: none; }
  .recent-item .title a:hover { color: #fff; }
  .recent-item .meta { font-size: 0.7rem; color: #555; margin-top: 2px; }
  .recent-item .tag {
    font-size: 0.65rem; color: #555; background: #0f0f0f;
    padding: 2px 8px; border-radius: 10px; margin-left: 8px; white-space: nowrap;
  }
  .recent-empty { text-align: center; color: #333; font-size: 0.8rem; padding: 1.5rem 0; }

  /* ── cog / settings button ── */
  .cog-btn {
    background: none; border: none; color: #333; padding: 4px;
    cursor: pointer; border-radius: 6px; line-height: 0;
    transition: all 0.15s;
  }
  .cog-btn:hover { color: #888; background: #141414; }
  .cog-btn svg { width: 18px; height: 18px; }

  /* ── settings overlay ── */
  .overlay {
    display: none; position: fixed; inset: 0; z-index: 100;
    background: rgba(0,0,0,0.6); backdrop-filter: blur(4px);
    justify-content: center; align-items: flex-start; padding-top: 8vh;
  }
  .overlay.open { display: flex; }
  .overlay-panel {
    background: #121212; border: 1px solid #2a2a2a; border-radius: 16px;
    width: 100%; max-width: 480px; max-height: 70vh; overflow-y: auto;
    padding: 1.5rem; position: relative;
  }
  .overlay-panel .close {
    position: absolute; top: 12px; right: 14px;
    background: none; border: none; color: #555; font-size: 1.2rem;
    cursor: pointer; padding: 4px 8px; border-radius: 6px; line-height: 1;
  }
  .overlay-panel .close:hover { color: #e0e0e0; background: #1c1c1c; }
  .overlay-panel h2 {
    font-size: 0.85rem; font-weight: 500; color: #888;
    margin-bottom: 1.25rem; text-transform: uppercase; letter-spacing: 0.05em;
  }
  .overlay-panel h3 {
    font-size: 0.7rem; font-weight: 500; color: #555;
    text-transform: uppercase; letter-spacing: 0.08em;
    margin-top: 1.5rem; margin-bottom: 0.75rem; padding-top: 1rem;
    border-top: 1px solid #1c1c1c;
  }
  .overlay-panel h3:first-of-type { border-top: none; margin-top: 0; padding-top: 0; }

  .setting-row {
    display: flex; justify-content: space-between; align-items: center;
    padding: 10px 0; border-bottom: 1px solid #1a1a1a;
  }
  .setting-row:last-child { border-bottom: none; }
  .setting-row .label { font-size: 0.85rem; color: #ccc; }
  .setting-row .desc { font-size: 0.7rem; color: #555; margin-top: 2px; }

  /* toggle switch */
  .toggle {
    position: relative; width: 40px; height: 22px; flex-shrink: 0;
    background: #2a2a2a; border-radius: 11px; cursor: pointer;
    transition: background 0.2s; border: none; padding: 0;
  }
  .toggle.on { background: #555; }
  .toggle::after {
    content: ""; position: absolute; top: 2px; left: 2px;
    width: 18px; height: 18px; border-radius: 50%;
    background: #666; transition: all 0.2s;
  }
  .toggle.on::after { left: 20px; background: #e0e0e0; }

  /* debug info */
  .debug-row {
    display: flex; justify-content: space-between; padding: 6px 0;
    font-size: 0.8rem; border-bottom: 1px solid #111;
  }
  .debug-row:last-child { border-bottom: none; }
  .debug-row .key { color: #666; }
  .debug-row .val { color: #aaa; font-family: "SF Mono","Fira Code",monospace; font-size: 0.75rem; }
  .debug-row .val.good { color: #4caf50; }
  .debug-row .val.warn { color: #ff9800; }

  .test-btn {
    margin-top: 1rem; width: 100%; padding: 8px;
    background: #1c1c1c; border: 1px solid #2a2a2a; border-radius: 8px;
    color: #888; font-size: 0.8rem; cursor: pointer; font-family: inherit;
    transition: all 0.15s;
  }
  .test-btn:hover { border-color: #444; color: #e0e0e0; }
  .test-btn:disabled { opacity: 0.4; cursor: not-allowed; }
  .test-result { margin-top: 8px; font-size: 0.75rem; color: #888; word-break: break-all; }

  @media (max-width: 480px) {
    .page { padding: 1rem; }
    .header { padding-top: 2vh; }
    .input-row { flex-direction: column; border-radius: 12px; }
    .input-row input { width: 100%; }
    .input-row button { width: 100%; }
    .overlay-panel { max-height: 85vh; margin: 0 1rem; }
  }
</style>
</head>
<body>

<div class="page">
  <div class="header">
    <div class="brand">
      <svg viewBox="0 0 32 32" fill="none">
        <rect x="2" y="8" width="28" height="18" rx="3" stroke="#555" stroke-width="1.5" fill="none"/>
        <polygon points="13,11 13,23 23,17" fill="#e0e0e0"/>
      </svg>
      <span>yt → obi</span>
    </div>
    <button class="cog-btn" id="settings-btn" title="settings / debug" onclick="openSettings()">
      <svg viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round">
        <circle cx="9" cy="9" r="2.5"/>
        <path d="M9 1.5v2M9 14.5v2M3.3 3.3l1.4 1.4M13.3 13.3l1.4 1.4M1.5 9h2M14.5 9h2M3.3 14.7l1.4-1.4M13.3 4.7l1.4-1.4"/>
      </svg>
    </button>
  </div>

  <form id="scrape-form">
    <div class="input-row">
      <input type="url" id="url-input" placeholder="Paste a YouTube URL" required autofocus>
      <button type="submit" id="submit-btn">→</button>
    </div>
    <div class="pills" id="pills">
      <span class="pill active" data-v="sources">📥 sources</span>
      <span class="pill" data-v="shared">📁 shared</span>
      <span class="pill" data-v="homelab-wiki">🔧 wiki</span>
      <span class="pill" data-v="personal-wiki">📝 personal</span>
      <span class="pill" data-v="real-estate">🏠 real-estate</span>
      <span class="pill" data-v="dental-msp">🦷 dental</span>
      <span class="pill" data-v="axiom-music">🎵 music</span>
    </div>
  </form>

  <div id="result" class="result"></div>

  <div class="recent" id="recent-section">
    <div class="recent-header"><h2>Recent</h2></div>
    <div id="recent-list"></div>
  </div>
</div>

<!--- settings overlay --->
<div class="overlay" id="settings-overlay">
  <div class="overlay-panel">
    <button class="close" onclick="closeSettings()">✕</button>
    <h2>settings</h2>

    <div class="setting-row">
      <div>
        <div class="label">Auto-fetch transcript</div>
        <div class="desc">Include transcript text in notes</div>
      </div>
      <button class="toggle on" id="toggle-transcript" onclick="this.classList.toggle('on')"></button>
    </div>
    <div class="setting-row">
      <div>
        <div class="label">Include description</div>
        <div class="desc">Add video description to notes</div>
      </div>
      <button class="toggle on" id="toggle-desc" onclick="this.classList.toggle('on')"></button>
    </div>

    <h3>info for nerds</h3>

    <div class="debug-row">
      <span class="key">service</span>
      <span class="val" id="debug-service">loading...</span>
    </div>
    <div class="debug-row">
      <span class="key">yt-dlp</span>
      <span class="val" id="debug-ytdlp">loading...</span>
    </div>
    <div class="debug-row">
      <span class="key">transcript api</span>
      <span class="val" id="debug-transcript">loading...</span>
    </div>
    <div class="debug-row">
      <span class="key">vault path</span>
      <span class="val" id="debug-vault">loading...</span>
    </div>
    <div class="debug-row">
      <span class="key">notes scraped</span>
      <span class="val" id="debug-count">loading...</span>
    </div>
    <div class="debug-row">
      <span class="key">default category</span>
      <span class="val" id="debug-category">loading...</span>
    </div>

    <button class="test-btn" id="test-btn" onclick="runTest()">Run test scrape</button>
    <div class="test-result" id="test-result"></div>
  </div>
</div>

<script>
  // ── pills ──
  const pills = document.querySelectorAll('.pill');
  let selectedCategory = 'sources';
  pills.forEach(p => {
    p.addEventListener('click', () => {
      pills.forEach(x => x.classList.remove('active'));
      p.classList.add('active');
      selectedCategory = p.dataset.v;
    });
  });

  // ── form ──
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
    result.className = 'result loading';
    result.innerHTML = '<span class="spinner"></span> Scraping...';

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
        result.className = 'result success';
        result.innerHTML = '<div class="path">' + esc(d.file) + '</div>'
          + '<a href="/view/' + encodeURIComponent(d.file) + '" target="_blank" class="view-link">View note →</a>';
        loadRecent();
      } else {
        result.className = 'result error';
        result.innerHTML = '✗ ' + esc(d.error);
      }
    } catch (err) {
      result.className = 'result error';
      result.innerHTML = '✗ ' + esc(err.message);
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

  // ── settings ──
  function openSettings() {
    document.getElementById('settings-overlay').classList.add('open');
    document.body.style.overflow = 'hidden';
    loadDebugInfo();
  }
  function closeSettings() {
    document.getElementById('settings-overlay').classList.remove('open');
    document.body.style.overflow = '';
  }
  document.getElementById('settings-overlay').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) closeSettings();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeSettings();
  });

  async function loadDebugInfo() {
    try {
      const r = await fetch('/debug');
      const d = await r.json();
      document.getElementById('debug-service').textContent = d.uptime || 'running';
      document.getElementById('debug-ytdlp').textContent = d.ytdlp_version || '?';
      document.getElementById('debug-transcript').textContent = d.transcript_api || '?';
      document.getElementById('debug-vault').textContent = d.vault_path || '?';
      document.getElementById('debug-count').textContent = d.notes_count + ' notes' || '?';
      document.getElementById('debug-category').textContent = selectedCategory;
      document.getElementById('debug-service').className = 'val good';
      document.getElementById('debug-transcript').className = d.transcript_ok ? 'val good' : 'val warn';
      document.getElementById('debug-ytdlp').className = 'val';
    } catch {}
  }

  async function runTest() {
    const tb = document.getElementById('test-btn');
    const tr = document.getElementById('test-result');
    tb.disabled = true;
    tr.textContent = 'Running...';
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

  // ── load recent ──
  async function loadRecent() {
    try {
      const r = await fetch('/recent');
      const d = await r.json();
      if (d.files && d.files.length > 0) {
        recent.innerHTML = d.files.map(f =>
          '<div class="recent-item">'
          + '<div class="info">'
          + '<div class="title"><a href="/view/' + encodeURIComponent(f.path) + '" target="_blank">' + esc(f.title) + '</a></div>'
          + '<div class="meta">' + esc(f.date) + ' · ' + esc(f.category) + '</div>'
          + '</div>'
          + '<span class="tag">' + esc(f.category) + '</span>'
          + '</div>'
        ).join('');
      } else {
        recent.innerHTML = '<div class="recent-empty">No scrapes yet</div>';
      }
    } catch {}
  }
  loadRecent();
</script>
</body>
</html>
"""


def get_recent_scrapes(limit=5):
    """List most recent scraped notes"""
    vault = Path(VAULT)
    files = []
    for p in vault.rglob("*.md"):
        rel = p.relative_to(vault)
        if not str(rel).startswith("."):
            mtime = p.stat().st_mtime
            files.append((mtime, str(rel)))
    files.sort(reverse=True)
    result = []
    for mtime, path in files[:limit]:
        name = Path(path).stem
        parts = path.split("/")
        category = parts[0] if len(parts) > 1 else ""
        from datetime import datetime
        dt = datetime.fromtimestamp(mtime)
        result.append({
            "path": path, "title": name,
            "date": dt.strftime("%Y-%m-%d %H:%M"),
            "category": category
        })
    return result


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
            ["/usr/local/bin/yt-to-obi", url, category],
            capture_output=True, text=True, timeout=120
        )
        output = result.stdout.strip() or result.stderr.strip()
        if result.returncode == 0 and "Written:" in output:
            file_path = output.split("Written:", 1)[1].strip()
            rel_path = file_path.replace(VAULT, "").lstrip("/")
            return jsonify({"ok": True, "file": rel_path, "output": output})
        else:
            return jsonify({"ok": False, "error": output or f"Exit code: {result.returncode}"})
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "Scrape timed out after 120s"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/recent")
def recent():
    return jsonify({"files": get_recent_scrapes()})


@app.route("/view/<path:filepath>")
def view(filepath):
    safe_path = Path(VAULT) / filepath
    safe_path = safe_path.resolve()
    if not str(safe_path).startswith(VAULT):
        return "Invalid path", 403
    if not safe_path.exists():
        return "Not found", 404
    content = safe_path.read_text()
    return f"<pre>{html.escape(content)}</pre>", 200, {"Content-Type": "text/plain; charset=utf-8"}




@app.route("/debug")
def debug():
    """Return debug/info for the settings panel"""
    import subprocess, datetime
    info = {
        "vault_path": VAULT,
        "uptime": "active",
        "transcript_api": "?",
        "transcript_ok": False,
        "ytdlp_version": "?",
        "notes_count": 0,
    }
    # Check yt-dlp version
    try:
        r = subprocess.run(["/opt/scraper-venv/bin/yt-dlp", "--version"],
            capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            info["ytdlp_version"] = r.stdout.strip()
    except: pass
    # Check youtube-transcript-api
    try:
        r = subprocess.run(
            ["/opt/scraper-venv/bin/python3", "-c",
             "from youtube_transcript_api import YouTubeTranscriptApi; print('ok')"],
            capture_output=True, text=True, timeout=5)
        info["transcript_api"] = "available" if r.returncode == 0 else "unavailable"
        info["transcript_ok"] = r.returncode == 0
    except:
        info["transcript_api"] = "error"
    # Count notes
    try:
        from pathlib import Path
        count = sum(1 for _ in Path(VAULT).rglob("*.md") if not str(_.relative_to(VAULT)).startswith("."))
        info["notes_count"] = count
    except: pass
    return jsonify(info)


@app.route("/test-scrape", methods=["POST"])
def test_scrape():
    """Run a quick test scrape to verify the pipeline"""
    import subprocess
    try:
        r = subprocess.run(
            ["/usr/local/bin/yt-to-obi", "https://www.youtube.com/watch?v=jNQXAC9IVRw", "sources"],
            capture_output=True, text=True, timeout=30
        )
        out = r.stdout.strip() or r.stderr.strip()
        if r.returncode == 0 and "Written:" in out:
            fpath = out.split("Written:", 1)[1].strip()
            rel = fpath.replace(VAULT, "").lstrip("/")
            return jsonify({"ok": True, "file": rel, "output": out})
        else:
            return jsonify({"ok": False, "error": out or f"exit {r.returncode}"})
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "timed out"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
