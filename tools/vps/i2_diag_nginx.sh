#!/usr/bin/env bash
# i2_diag_nginx.sh -- READ-ONLY diagnosis of the /eva/mcp bearer gate (I2, owner FRÅGESTOPP).
# Mutates nothing. Prints no secrets: the bearer value is redacted from the nginx -T dump
# before anything is printed, and curl never echoes request headers.
set -uo pipefail
SITE=/etc/nginx/sites-available/grc.eveverified.com
TOK=/opt/eva-demo/nginx-bearer.txt
H=https://grc.eveverified.com/eva/mcp
# Redaction (broadened after the 2026-09-30 exposure finding): masks every quoted comparison
# literal in if(...) conditions, every Bearer/Basic value, and key/token/secret/password
# assignments. Values are never printed, hashed or stored.
red() { sed -E \
  -e 's/(!=|=|~\*?|!~\*?)[[:space:]]*"[^"]*"/\1 "<REDACTED>"/g' \
  -e 's/((Bearer|Basic)[[:space:]]+)[^";[:space:]]+/\1<REDACTED>/g' \
  -e 's/(([Kk][Ee][Yy]|[Tt][Oo][Kk][Ee][Nn]|[Ss][Ee][Cc][Rr][Ee][Tt]|[Pp][Aa][Ss][Ss][Ww][Oo][Rr][Dd])[A-Za-z_]*[[:space:]]+)[^;[:space:]]+;/\1<REDACTED>;/g'; }

echo "== 1. site file: where the block sits =="
grep -n 'server_name\|listen\|location\|eva/mcp\|include' "$SITE"

echo "== 2. effective configuration (nginx -T, bearer REDACTED, routing-relevant lines) =="
sudo nginx -T 2>/dev/null | red | grep -n '^# configuration file\|server_name\|listen \|location\|proxy_pass\|include /etc/nginx/snippets\|return \|if ('

echo "== 3. nginx process / reload state =="
systemctl status nginx --no-pager 2>/dev/null | head -4
sudo journalctl -u nginx -n 10 --no-pager 2>/dev/null | tail -5

probe() {  # label, curl args... -> status line, Server header, content-type, body head
  local label=$1; shift
  local hdr body code; hdr=$(mktemp); body=$(mktemp)
  curl -sS -m 15 -o "$body" -D "$hdr" "$@" 2>>"$body"
  code=$(sed -n '1p' "$hdr" | tr -d '\r')
  echo "-- $label: $code | server=$(grep -i '^server:' "$hdr" | tr -d '\r' | cut -d' ' -f2-) | ctype=$(grep -i '^content-type:' "$hdr" | tr -d '\r' | cut -d' ' -f2-)"
  echo "   body: $(head -c 160 "$body" | tr '\n' ' ')"
  rm -f "$hdr" "$body"
}
INIT='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"i2-diag","version":"0"}}}'
MCPH=(-H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' -H 'MCP-Protocol-Version: 2025-11-25')

echo "== 4. auth boundary through HTTPS (nginx rejection vs upstream answer) =="
probe "no token, bare POST"            -X POST "$H"
probe "wrong token, bare POST"         -X POST -H 'Authorization: Bearer wrong' "$H"
probe "correct token, bare POST"       -X POST -H "Authorization: Bearer $(cat "$TOK")" "$H"
probe "correct token, MCP initialize"  -X POST -H "Authorization: Bearer $(cat "$TOK")" "${MCPH[@]}" -d "$INIT" "$H"

echo "== 5. the upstreams directly on loopback (what each one answers) =="
probe "eve-mcp bare POST /mcp"         -X POST http://127.0.0.1:8765/mcp
probe "eve-mcp MCP initialize /mcp"    -X POST "${MCPH[@]}" -d "$INIT" http://127.0.0.1:8765/mcp
probe "GRC GET /eva/mcp"               http://127.0.0.1:8002/eva/mcp

echo "== DIAG_DONE (read-only) =="
