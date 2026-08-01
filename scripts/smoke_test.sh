#!/bin/bash
# smoke_test.sh — verify the LIVE Quarry deployment on LXC 101 (192.168.1.21:5000).
# Run from any host with network + SSH to pve-m910-01 (.13).
# Usage: ./smoke_test.sh [HOST_IP]   (default 192.168.1.21)
set -uo pipefail

HOST="${1:-192.168.1.21}"
BASE="http://$HOST:5000"
PASS=0; FAIL=0
ok()   { echo "  ✅ $1"; PASS=$((PASS+1)); }
bad()  { echo "  ❌ $1"; FAIL=$((FAIL+1)); }

echo "== Quarry smoke test ($BASE) =="

# 1. Home page serves
CODE=$(curl -s -m 10 -o /dev/null -w '%{http_code}' "$BASE/")
[ "$CODE" = "200" ] && ok "GET / -> 200" || bad "GET / -> $CODE"

# 2. Scrape form present (paste bar + save pills)
PAGE_HTML=$(curl -s -m 10 "$BASE/")
if grep -q "renderScrapeForm" <<< "$PAGE_HTML"; then
  ok "scrape form rendered"
else
  bad "scrape form missing"
fi

# 3. /api/vault lists all 8 categories incl ish-d
VAULT_JSON=$(curl -s -m 10 "$BASE/api/vault")
grep -q '"ish-d"' <<< "$VAULT_JSON" && ok "/api/vault has ish-d" || bad "/api/vault missing ish-d"
N=$(echo "$VAULT_JSON" | grep -o '"label"' | wc -l)
[ "$N" -ge 8 ] && ok "/api/vault $N categories" || bad "/api/vault only $N categories"

# 4. /debug reports yt-dlp (key is "ytdlp_version")
DEBUG_JSON=$(curl -s -m 10 "$BASE/debug")
grep -qi "ytdlp_version" <<< "$DEBUG_JSON" && ok "/debug yt-dlp present" || bad "/debug missing yt-dlp"

# 5. /recent parses as JSON with scrapes array
RECENT=$(curl -s -m 10 "$BASE/recent")
echo "$RECENT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert 'scrapes' in d, 'no scrapes key'" 2>/dev/null \
  && ok "/recent valid JSON" || bad "/recent invalid JSON"

# 6. /api/health reports all three services
HEALTH=$(curl -s -m 10 "$BASE/api/health")
MISSING=""
for K in obsidian hermes worker; do
  grep -q "\"$K\"" <<< "$HEALTH" || MISSING="$MISSING $K"
done
[ -z "$MISSING" ] && ok "/api/health has obsidian/hermes/worker" || bad "/api/health missing:$MISSING"

# 7. /api/check rejects a non-YouTube URL
CHECK=$(curl -s -m 10 "$BASE/api/check?url=notaurl")
grep -q '"valid":false' <<< "$CHECK" && ok "/api/check rejects bad url" || bad "/api/check bad url -> $CHECK"

# 8. /api/settings exposes the default destination
SETTINGS=$(curl -s -m 10 "$BASE/api/settings")
grep -q '"default_category"' <<< "$SETTINGS" && ok "/api/settings has default_category" || bad "/api/settings missing default_category"

# 9. Deployed source integrity (via LXC)
ssh -o ConnectTimeout=8 -o StrictHostKeyChecking=no root@192.168.1.13 \
  "pct exec 101 -- python3 -m py_compile /opt/quarry/webui.py /opt/quarry/quarry && echo PYOK" 2>/dev/null | grep -q PYOK \
  && ok "py_compile webui.py + quarry" || bad "py_compile failed"

ssh -o ConnectTimeout=8 -o StrictHostKeyChecking=no root@192.168.1.13 \
  "pct exec 101 -- cat /opt/quarry/index.html" 2>/dev/null > /tmp/quarry-deployed-index.html
python3 "$(dirname "$0")/check_js_balance.py" /tmp/quarry-deployed-index.html 2>/dev/null | grep -q BALANCED \
  && ok "JS balance on deployed index.html" || bad "JS balance check failed"
rm -f /tmp/quarry-deployed-index.html

echo "== Result: $PASS passed, $FAIL failed =="
[ "$FAIL" -eq 0 ]
