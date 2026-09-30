#!/usr/bin/env bash
# i2_backend.sh -- EVA demo backend on the VPS (Phase 1, increment I2).
#
#   Internet -> https://grc.eveverified.com/eva/mcp (bearer, nginx) -> EVE MCP v1 (127.0.0.1:8765)
#            -> EVE eve-core-v1 (127.0.0.1:8012, external runtime store). EVE is never exposed.
#
# One subcommand per step; every step measures before it mutates and STOPs (exit 3) on the
# first deviation. Nothing under /opt/eve-grc, no existing pm2 process and no existing nginx
# location is touched. Secrets (PRE_ACTION_READ_TOKEN, nginx bearer) are generated on the
# host into 0600 files and are never printed; only permissions and sha256 are reported.
#
# Usage (from the workstation):  ssh ubuntu@<vps> "bash /opt/eva-demo/incoming/i2_backend.sh <step>"
# Steps in order: clone | venv | suite | mcp | state | secrets | scenarios [--save] | units |
#                 accept | nginx | verify | status
set -euo pipefail

ROOT=/opt/eva-demo
INC=$ROOT/incoming
EVE_DIR=$ROOT/eve-core-v1
MCP_DIR=$ROOT/eve-mcp
STORE=$ROOT/eve_store
EVID=$ROOT/evidence
EXPECTED_EVE_TREE=a698922c9fd740c4b114e572a626380abf1590a4
EXPECTED_MCP_TREE=cbdcd191710c472f7706a9487f31eef3cfd1821d
EVE_PORT=8012
MCP_PORT=8765
GRC_VENV=/opt/eve-grc/venv
SITE=/etc/nginx/sites-available/grc.eveverified.com
SNIPPET=/etc/nginx/snippets/eva-mcp-bearer.conf
PUBLIC_HOST=grc.eveverified.com
PUBLIC_IP=185.20.15.189

stop() { echo "STOP: $*" >&2; exit 3; }
need() { [ -e "$1" ] || stop "missing $1 (run the previous step first)"; }
ts() { date -u +%Y%m%dT%H%M%SZ; }

pm2_state() {  # name status restarts cwd -- for the non-interference comparison
  # pm2 7.0.1 CLI prints its daemon-version warning on stdout BEFORE the JSON array
  # (daemon 6.0.14 in memory); parse from the first '[' and never run 'pm2 update'.
  pm2 jlist 2>/dev/null | python3 -c 'import json,sys
raw=sys.stdin.read(); raw=raw[raw.find("["):]
for p in sorted(json.loads(raw), key=lambda p: p["name"]):
    e=p["pm2_env"]; print(p["name"], e["status"], e.get("restart_time"), e.get("pm_cwd"))'
}

step=${1:-}
case "$step" in

clone)
  [ -d "$EVE_DIR" ] && stop "$EVE_DIR already exists; this step never overwrites"
  need "$INC/eve-core-v1.bundle"
  git bundle list-heads "$INC/eve-core-v1.bundle" | grep -q 'refs/tags/eve-core-v1$' || stop "bundle does not carry refs/tags/eve-core-v1"
  git clone -q --branch eve-core-v1 "$INC/eve-core-v1.bundle" "$EVE_DIR"
  head=$(git -C "$EVE_DIR" rev-parse HEAD); tree=$(git -C "$EVE_DIR" rev-parse 'HEAD^{tree}')
  echo "HEAD $head"; echo "tree $tree"
  [ "$tree" = "$EXPECTED_EVE_TREE" ] || stop "tree $tree != $EXPECTED_EVE_TREE"
  echo "CLONE_OK tree == eve-core-v1"
  ;;

venv)
  need "$EVE_DIR"; [ -d "$ROOT/venv" ] && stop "$ROOT/venv already exists"
  "$GRC_VENV/bin/pip" freeze > "$INC/grc-venv-freeze.txt"      # read-only on the GRC venv
  echo "grc venv: $("$GRC_VENV/bin/python" --version), $(wc -l < "$INC/grc-venv-freeze.txt") lines"
  if grep -Ev '^[A-Za-z0-9_.-]+==' "$INC/grc-venv-freeze.txt" | grep -q .; then
    echo "non-pinned lines in the GRC freeze (editable / URL / VCS):"; grep -Ev '^[A-Za-z0-9_.-]+==' "$INC/grc-venv-freeze.txt"
    stop "GRC environment is not exactly reproducible from pip freeze; owner decision required, no substitution"
  fi
  python3 -m venv "$ROOT/venv"
  "$ROOT/venv/bin/pip" install -q --upgrade pip >/dev/null 2>&1 || true
  "$ROOT/venv/bin/pip" install -q -r "$INC/grc-venv-freeze.txt" || stop "pip install of the GRC freeze failed"
  if ! grep -q '^pytest==' "$INC/grc-venv-freeze.txt"; then
    "$ROOT/venv/bin/pip" install -q pytest || stop "pytest install failed"
    echo "pytest added for the regression gate: $("$ROOT/venv/bin/python" -m pytest --version 2>&1)"
  fi
  "$ROOT/venv/bin/pip" freeze > "$INC/demo-venv-freeze.txt"
  echo "demo venv vs GRC freeze (diff, expected: only pytest + its dependencies):"
  diff <(grep -E '^[A-Za-z0-9_.-]+==' "$INC/grc-venv-freeze.txt" | sort) <(grep -E '^[A-Za-z0-9_.-]+==' "$INC/demo-venv-freeze.txt" | sort) || true
  echo "VENV_OK"
  ;;

suite)
  # OWNER DECISION A (2026-09-30): the pinned tree's full suite is 1293 on the accepted
  # workstation runtime. On this Linux VPS the H6 protected trusted-git companion
  # (MACHINE_BOUND_CONFIG D:\EVE_RUNNER\trusted_git.json, eve_trusted_git.py:32) does not
  # exist by design, so exactly ten H4/H5 sealer tests fail with trusted_git_unconfigured.
  # ALL 1293 tests are still run; nothing is deselected, xfailed or patched. The gate is
  # the EXACT qualified outcome below; anything else is a STOP. Runtime modules never
  # import the sealer (grc_api.py and every determination/pre-action module: 0 imports).
  need "$ROOT/venv"; need "$EVE_DIR"; mkdir -p "$EVID"
  cd "$EVE_DIR"
  run_ts=$(ts); log="$EVID/SUITE_VPS_${run_ts}.txt"
  set +e; COLUMNS=400 PYTHONDONTWRITEBYTECODE=1 "$ROOT/venv/bin/python" -m pytest -q -p no:cacheprovider -rf --tb=short > "$log" 2>&1; rc=$?; set -e
  tail -14 "$log"; echo "pytest exit code $rc (full output: $log)"
  python3 - "$log" "$EVID/SUITE_VPS_${run_ts}.json" "$run_ts" "$rc" "$EXPECTED_EVE_TREE" "$INC/demo-venv-freeze.txt" "$INC/grc-venv-freeze.txt" <<'PY'
import hashlib, json, re, sys
log, out, run_ts, rc, tree, demo_freeze, grc_freeze = sys.argv[1:8]
EXPECTED = {
 "tests/test_correspondence_role.py::test_sealer_apply_matches_ordinary_git",
 "tests/test_correspondence_role.py::test_sealer_one_byte_eol_change_changes_tree",
 "tests/test_correspondence_role.py::test_sealer_rederivation_gate_rejects_declared_tree",
 "tests/test_correspondence_role.py::test_sealer_does_not_mutate_authoritative_repo",
 "tests/test_ref_non_authority.py::test_valid_commit_sha40_accepted",
 "tests/test_ref_non_authority.py::test_valid_tree_sha40_refused_not_commit",
 "tests/test_ref_non_authority.py::test_valid_blob_sha40_refused_not_commit",
 "tests/test_ref_non_authority.py::test_nonexistent_sha40_refused_not_commit",
 "tests/test_ref_non_authority.py::test_rederivation_gate_inherits_commit_gate",
 "tests/test_ref_non_authority.py::test_accepted_commit_path_still_derives_and_gates",
}
REASON = "trusted_git_unconfigured"
text = open(log, encoding="utf-8", errors="replace").read()
summary = re.search(r"^(\d+) failed, (\d+) passed(.*)$", text, re.M)
failed_lines = re.findall(r"^FAILED .*$", text, re.M)
failed_ids = {l.split()[1] for l in failed_lines}
wrong_reason = [l.split()[1] for l in failed_lines if REASON not in l]
reason_hits = text.count(REASON)
errors = re.findall(r"^ERROR ", text, re.M)
problems = []
if not summary: problems.append("no '<n> failed, <m> passed' summary line")
else:
    if summary.group(1) != "10" or summary.group(2) != "1283": problems.append(f"counts {summary.group(1)} failed / {summary.group(2)} passed != 10 / 1283")
    if "error" in summary.group(3): problems.append("errors present in summary")
if failed_ids != EXPECTED: problems.append(f"failed set differs: unexpected={sorted(failed_ids-EXPECTED)} missing={sorted(EXPECTED-failed_ids)}")
if wrong_reason: problems.append(f"failures without reason '{REASON}' on their FAILED line: {wrong_reason}")
if reason_hits < 10: problems.append(f"reason '{REASON}' seen {reason_hits} times, expected >= 10")
if errors: problems.append(f"{len(errors)} collection/setup ERROR lines")
record = {
 "record_kind": "eva_i2_vps_suite", "record_schema_version": "eva-vps-suite-1.0", "run_utc": run_ts,
 "eve_tree": tree, "host": "VPS 185.20.15.189 (Linux, Python 3.12.3 demo venv)",
 "gate": "SUITE_QUALIFIED_PASS (owner decision A, 2026-09-30)",
 "all_tests_run": True, "deselected_or_modified": "NONE",
 "result": {"passed": int(summary.group(2)) if summary else None, "failed": int(summary.group(1)) if summary else None, "pytest_exit_code": int(rc)},
 "expected_environment_bound_failures": sorted(EXPECTED),
 "failure_reason": "eve_correspondence_sealer.CorrespondenceSealError: trusted_git_unconfigured -- eve_trusted_git.TRUSTED_GIT_CONFIG_PATH = D:\\EVE_RUNNER\\trusted_git.json (MACHINE_BOUND_CONFIG, H6 protected runtime companion) does not exist on this Linux host",
 "classification": "ENVIRONMENT_BOUND_H6_TRUSTED_GIT_COMPANION_ABSENT",
 "not_needed_by_eva_pre_action_path": "grc_api.py and every determination/pre-action/handling module import neither eve_correspondence_sealer nor eve_trusted_git (measured 2026-09-30)",
 "accepted_full_regression_reference": "workstation runtime with H6 companion: 1293 passed (CORE_FREEZE_v1, eve-mcp ACCEPTANCE_2026-09-30T122051Z)",
 "log_file": log, "log_sha256": hashlib.sha256(open(log,'rb').read()).hexdigest(),
 "demo_venv_freeze_sha256": hashlib.sha256(open(demo_freeze,'rb').read()).hexdigest(),
 "grc_venv_freeze_sha256": hashlib.sha256(open(grc_freeze,'rb').read()).hexdigest(),
 "problems": problems,
}
record["record_sha256"] = hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",",":"), ensure_ascii=False).encode()).hexdigest()
with open(out, "x", encoding="utf-8") as fh: json.dump(record, fh, indent=2, sort_keys=True); fh.write("\n")
print(f"suite record {out} record_sha256={record['record_sha256'][:16]}...")
if problems:
    print("STOP: " + "; ".join(problems)); sys.exit(3)
print("SUITE_QUALIFIED_PASS 1283 passed / 10 expected environment-bound failures (H6 trusted-git companion absent on this host); workstation reference remains 1293")
PY
  ;;

mcp)
  [ -d "$MCP_DIR" ] && stop "$MCP_DIR already exists"
  need "$INC/eve-mcp-v1.zip"; need "$INC/verify_vendor.py"
  mkdir "$MCP_DIR" && unzip -q "$INC/eve-mcp-v1.zip" -d "$MCP_DIR"
  python3 "$INC/verify_vendor.py" --vendor "$MCP_DIR" | tail -1 | tee "$INC/verify_vendor.last"
  grep -q "VENDOR_VERIFY PASS" "$INC/verify_vendor.last" || stop "vendored eve-mcp is not the frozen tag"
  python3 -m venv "$ROOT/venv-mcp"
  "$ROOT/venv-mcp/bin/pip" install -q --upgrade pip >/dev/null 2>&1 || true
  "$ROOT/venv-mcp/bin/pip" install -q -r "$MCP_DIR/requirements.lock.txt" || stop "eve-mcp lock install failed"
  "$ROOT/venv-mcp/bin/pip" install -q -e "$MCP_DIR" --no-deps || stop "eve-mcp editable install failed"
  set +e; out=$("$ROOT/venv-mcp/bin/python" -m pytest -q "$MCP_DIR/tests" 2>&1); rc=$?; set -e
  echo "$out" | tail -15; echo "pytest exit code $rc"
  echo "$out" | tail -1 | grep -q '88 passed' || stop "eve-mcp tests did not report 88 passed"
  echo "MCP_OK tree $EXPECTED_MCP_TREE, 88 passed"
  ;;

state)
  mkdir -p "$INC/state"
  f="$INC/state/pm2_$(ts).txt"; pm2_state > "$f"; echo "pm2 state snapshot -> $f ($(wc -l < "$f") processes)"
  cp -p "$HOME/.pm2/dump.pm2" "$INC/state/dump.pm2.$(ts)" 2>/dev/null && sha256sum "$INC/state/dump.pm2."* | tail -1 || echo "no ~/.pm2/dump.pm2 present"
  ss -ltn | awk 'NR>1{print $4}' | sort > "$INC/state/listen_$(ts).txt"
  echo "STATE_OK"
  ;;

secrets)
  [ -e "$ROOT/env.eve" ] && stop "$ROOT/env.eve exists; secrets are never regenerated by this step"
  mkdir -p "$STORE" "$EVID"
  umask 077
  { echo "EVE_RUNTIME_STORE_ROOT=$STORE"; echo "PRE_ACTION_READ_TOKEN=$(openssl rand -hex 24)"; } > "$ROOT/env.eve"
  {
    echo "EVE_MCP_EVE_BASE_URL=http://127.0.0.1:$EVE_PORT"; echo "EVE_MCP_TIMEOUT_SECONDS=10"
    echo "EVE_MCP_DECLARED_TAG=eve-core-v1"; echo "EVE_MCP_DECLARED_TREE=$EXPECTED_EVE_TREE"
    echo "EVE_MCP_POLICY_REGISTRY=$MCP_DIR/policies/policy_registry_v1.json"
    echo "EVE_MCP_DEFAULT_POLICY_REF=eve-mcp-demo-policy-v1"; echo "EVE_MCP_HOST=127.0.0.1"; echo "EVE_MCP_PORT=$MCP_PORT"
  } > "$ROOT/env.mcp"
  openssl rand -hex 24 > "$ROOT/nginx-bearer.txt"
  ls -l "$ROOT/env.eve" "$ROOT/env.mcp" "$ROOT/nginx-bearer.txt"
  echo "nginx-bearer sha256 $(sha256sum "$ROOT/nginx-bearer.txt" | cut -c1-16)... (value never printed)"
  echo "SECRETS_OK"
  ;;

scenarios)
  need "$ROOT/env.eve"; need "$ROOT/venv"
  set -a; . "$ROOT/env.eve"; set +a
  cd "$ROOT"
  "$ROOT/venv/bin/python" "$MCP_DIR/scenarios/build_scenario_chains.py" --eve-checkout "$EVE_DIR" \
      --expected-tree "$EXPECTED_EVE_TREE" --scenarios "$MCP_DIR/scenarios/scenarios_v1.json" \
      --evidence-dir "$EVID" ${2:-}
  ;;

units)
  need "$ROOT/env.eve"; need "$ROOT/env.mcp"; need "$ROOT/venv"; need "$ROOT/venv-mcp"
  for u in eva-eve eva-mcp; do [ -e "/etc/systemd/system/$u.service" ] && stop "$u.service already exists"; done
  ss -ltn | grep -Eq ":($EVE_PORT|$MCP_PORT) " && stop "port $EVE_PORT or $MCP_PORT already in use"
  before=$(pm2_state)
  sudo tee /etc/systemd/system/eva-eve.service >/dev/null <<UNIT
[Unit]
Description=EVA demo backend: EVE eve-core-v1 (loopback only, external runtime store)
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=$EVE_DIR
EnvironmentFile=$ROOT/env.eve
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart=$ROOT/venv/bin/python -m uvicorn grc_api:app --host 127.0.0.1 --port $EVE_PORT
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT
  sudo tee /etc/systemd/system/eva-mcp.service >/dev/null <<UNIT
[Unit]
Description=EVA demo backend: EVE MCP v1 (loopback only)
After=network.target eva-eve.service

[Service]
Type=simple
User=ubuntu
WorkingDirectory=$MCP_DIR
EnvironmentFile=$ROOT/env.mcp
ExecStart=$ROOT/venv-mcp/bin/python -m eve_mcp.server
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT
  sudo systemctl daemon-reload
  sudo systemctl enable --now eva-eve.service eva-mcp.service
  sleep 4
  systemctl is-active eva-eve.service eva-mcp.service
  ss -ltnp | grep -E ":($EVE_PORT|$MCP_PORT) " || stop "services not listening"
  ss -ltn | grep -E ":($EVE_PORT|$MCP_PORT) " | grep -v '127.0.0.1' && stop "a service listens outside loopback" || true
  code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$EVE_PORT/api/chain/EVE-MCP-DEMO-A-2026-001")
  echo "EVE loopback GET chain A -> HTTP $code"; [ "$code" = "200" ] || stop "EVE does not serve the scenario chain (run scenarios --save first?)"
  after=$(pm2_state)
  [ "$before" = "$after" ] || { echo "$before" > "$INC/pm2_before.txt"; echo "$after" > "$INC/pm2_after.txt"; stop "pm2 process set changed during units (see incoming/pm2_before/after)"; }
  echo "pm2: unchanged ($(echo "$after" | wc -l) processes, same names/status/restart counts)"
  echo "UNITS_OK"
  ;;

accept)
  # The harness's internal full-suite gate requires exit 0 and is NOT used on the VPS
  # (owner decision A): the suite evidence is the identity-bound SUITE_VPS_<ts>.json record.
  need "$ROOT/env.eve"; need "$ROOT/venv-mcp"
  ls "$EVID"/SUITE_VPS_*.json >/dev/null 2>&1 || stop "no SUITE_VPS record; run 'suite' first"
  set -a; . "$ROOT/env.eve"; set +a
  cd "$ROOT"
  "$ROOT/venv-mcp/bin/python" "$MCP_DIR/acceptance/run_acceptance.py" --eve-checkout "$EVE_DIR" \
      --expected-tree "$EXPECTED_EVE_TREE" --eve-base-url "http://127.0.0.1:$EVE_PORT" \
      --mcp-url "http://127.0.0.1:$MCP_PORT/mcp" --registry "$MCP_DIR/policies/policy_registry_v1.json" \
      --policy-ref eve-mcp-demo-policy-v1 --scenarios "$MCP_DIR/scenarios/scenarios_v1.json" \
      --evidence-dir "$EVID"
  ;;

nginx)
  ls "$EVID"/ACCEPTANCE_*.json >/dev/null 2>&1 || stop "no acceptance record yet; nginx exposure requires PHASE1_ACCEPTANCE_PASS first"
  grep -l PHASE1_ACCEPTANCE_PASS "$EVID"/ACCEPTANCE_*.json >/dev/null || stop "no PASS acceptance record"
  need "$ROOT/nginx-bearer.txt"; [ -e "$SNIPPET" ] && stop "$SNIPPET exists"
  grep -q '/eva/mcp' "$SITE" && stop "site already contains /eva/mcp"
  [ "$(grep -c '    location / {' "$SITE")" = "1" ] || stop "site file shape not as measured (expected exactly one 'location / {')"
  bak="$INC/grc.eveverified.com.bak-$(ts)"; sudo cp -p "$SITE" "$bak"; echo "site backup $bak ($(sha256sum "$bak" | cut -c1-16)..., secret-free)"
  sudo mkdir -p /etc/nginx/snippets
  printf 'if ($http_authorization != "Bearer %s") { return 401; }\n' "$(cat "$ROOT/nginx-bearer.txt")" | sudo install -m 600 -o root -g root /dev/stdin "$SNIPPET"
  sudo ls -l "$SNIPPET"
  sudo python3 - "$SITE" "$SNIPPET" "$MCP_PORT" <<'PY'
import sys
site, snippet, port = sys.argv[1], sys.argv[2], sys.argv[3]
s = open(site).read()
block = ("    location = /eva/mcp {\n"
         f"        include {snippet};\n"
         f"        proxy_pass http://127.0.0.1:{port}/mcp;\n"
         "        proxy_http_version 1.1;\n"
         f"        proxy_set_header Host 127.0.0.1:{port};\n"
         '        proxy_set_header Connection "";\n'
         "        proxy_buffering off;\n"
         "        proxy_read_timeout 120s;\n"
         "    }\n\n")
assert s.count("    location / {") == 1
open(site, "w").write(s.replace("    location / {", block + "    location / {", 1))
print("site: /eva/mcp location inserted before location /")
PY
  sudo nginx -t || { sudo cp -p "$bak" "$SITE"; sudo nginx -t; stop "nginx -t failed; site restored from backup"; }
  sudo systemctl reload nginx
  # Bounded settle-loop (owner GO 2026-09-30): systemctl reload returns when SIGHUP is sent,
  # not when new workers serve. Readiness = unauthenticated /eva/mcp returns exactly 401,
  # max 10 s. This loop is NOT acceptance evidence; nginx-check below is.
  c=none
  for i in 1 2 3 4 5 6 7 8 9 10; do
    c=$(curl -s -m 5 -o /dev/null -w '%{http_code}' -X POST "https://$PUBLIC_HOST/eva/mcp")
    [ "$c" = "401" ] && break; sleep 1
  done
  [ "$c" = "401" ] || stop "nginx did not settle to 401 within 10 s after reload (last HTTP $c)"
  bash "$0" nginx-check
  ;;

nginx-check)
  # HARD GATE (owner FRÅGESTOPP 2026-09-30): NGINX_GATE_OK is emitted only when every measured
  # value matches; any mismatch is a STOP (exit 3). Never interpret, never soften.
  need "$ROOT/nginx-bearer.txt"
  local_init='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"i2-gate","version":"0"}}}'
  no=$(curl -s -m 15 -o /dev/null -w '%{http_code}' -X POST "https://$PUBLIC_HOST/eva/mcp")
  wrong=$(curl -s -m 15 -o /dev/null -w '%{http_code}' -X POST -H 'Authorization: Bearer wrong' "https://$PUBLIC_HOST/eva/mcp")
  ok=$(curl -s -m 15 -o /dev/null -w '%{http_code}' -X POST -H "Authorization: Bearer $(cat "$ROOT/nginx-bearer.txt")" \
       -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' -H 'MCP-Protocol-Version: 2025-11-25' \
       -d "$local_init" "https://$PUBLIC_HOST/eva/mcp")
  grc=$(curl -s -m 15 -o /dev/null -w '%{http_code}' "https://$PUBLIC_HOST/chain/pre-action")
  echo "no-token=$no  wrong-token=$wrong  correct-token+MCP-initialize=$ok  grc-page=$grc"
  [ "$no" = "401" ]    || stop "no-token gate: HTTP $no != 401"
  [ "$wrong" = "401" ] || stop "wrong-token gate: HTTP $wrong != 401"
  [ "$ok" = "200" ]    || stop "correct token + MCP initialize: HTTP $ok != 200"
  [ "$grc" = "200" ]   || stop "existing GRC page: HTTP $grc != 200"
  echo "NGINX_GATE_OK"
  ;;

verify)
  echo "loopback listeners:"; ss -ltn | grep -E ":($EVE_PORT|$MCP_PORT) "
  ss -ltn | grep -E ":($EVE_PORT|$MCP_PORT) " | grep -v '127.0.0.1:' && stop "a demo service listens outside loopback" || true
  for p in $EVE_PORT $MCP_PORT; do
    if curl -s -m 5 -o /dev/null "http://$PUBLIC_IP:$p/"; then stop "port $p reachable on the public IP"; else echo "public $PUBLIC_IP:$p -> not reachable (expected)"; fi
  done
  bash "$0" nginx-check
  sudo test "$(sudo stat -c '%a %U' "$SNIPPET")" = "600 root" || stop "$SNIPPET is not 600 root"
  for f in "$ROOT/env.eve" "$ROOT/env.mcp" "$ROOT/nginx-bearer.txt"; do
    [ "$(stat -c '%a %U' "$f")" = "600 ubuntu" ] || stop "$f is not 600 ubuntu"
  done
  sudo grep -q 'Bearer' "$SITE" && stop "site file contains a bearer literal" || true
  for b in "$INC"/grc.eveverified.com.bak-*; do grep -q 'Bearer' "$b" && stop "backup $b contains a bearer literal" || true; done
  echo "secret-bearing files: snippet 600 root; env.eve/env.mcp/nginx-bearer.txt 600 ubuntu; site file + backups bearer-free"
  echo "VERIFY_OK"
  ;;

probe)
  need "$ROOT/venv-mcp"; need "$INC/i2_remote_probe.py"
  "$ROOT/venv-mcp/bin/python" "$INC/i2_remote_probe.py"
  ;;

status)
  systemctl is-active eva-eve.service eva-mcp.service 2>/dev/null || true
  ss -ltn | grep -E ":($EVE_PORT|$MCP_PORT) " || echo "not listening"
  ls "$EVID" 2>/dev/null || true
  ;;

*)
  echo "usage: $0 {clone|venv|suite|mcp|state|secrets|scenarios [--save]|units|accept|nginx|nginx-check|verify|probe|status}" >&2; exit 2 ;;
esac
