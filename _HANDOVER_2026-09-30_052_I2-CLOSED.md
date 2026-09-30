# HANDOVER — PROJECT 052_eva — 2026-09-30 — I1 + I2 CLOSED, I3 NOT STARTED

```
CLASS    NAVIGATION ARTIFACT (PROJECT TRACK)
STATUS   FROZEN SNAPSHOT
DATE     2026-09-30
```

**HANDOFF MAY POINT TO STATE. HANDOFF MUST NOT ASSERT CURRENT STATE.**

Every identity below was measured on 2026-09-30 in the session that wrote this file, unless it is
labelled OWNER_DECISION or OWNER_REPORTED. Measure again before relying on it. If the disk or a
remote differs: STOP and report. This file is immutable; a later state gets a later dated handover.

Predecessor: none. This is the first dated handover of this track; before it, the track had only
`_HANDOVER_CURRENT.md`, which moved without a dated handover (deviation, section 5).

---

## 1. WHAT THIS PROJECT IS

EVA -- Evidence Verification Agent, powered by EVE. A downstream, self-contained project track:
EVA may propose consequential actions; a deterministic gate asks EVE (through the frozen EVE MCP v1)
before any such action and lets it run only on `allow`. EVA proposes, EVE decides, the gate enforces.
EVA is not Alexa+.

Built on two immutable dependencies, neither modified here:

```
EVE MCP v1   tag eve-mcp-v1   tree cbdcd191710c472f7706a9487f31eef3cfd1821d   (vendored at vendor/eve-mcp)
EVE core     tag eve-core-v1  tree a698922c9fd740c4b114e572a626380abf1590a4   (never vendored)
             = ACCEPTED_BASELINE_v21 member #0 ("frozen EVE Core, tag eve-core-v1")
```

---

## 2. STATE AT THIS SNAPSHOT

```
I1   CLOSED  (OWNER_DECISION 2026-09-30)
I2   CLOSED  (OWNER_DECISION 2026-09-30)
I3   NOT_STARTED
```

### Repository

```
local            D:\EVE11\Projects\052_eva
remote           https://github.com/elekto-energy/eva.git (private)
root commit      2a106fd21d63133a7dee7913600c98de1afec3ce   tree 95e99aa13f1babb9a6bbd13e27ed382038cdc1c1
                 git ls-tree HEAD vendor/eve-mcp -> 040000 tree cbdcd191710c472f7706a9487f31eef3cfd1821d
I2 evidence      a22d5e5 (15 files: evidence/i2/ x12, tools/vps/ x3)
main             95bb7392d2fb4065a27ea931b1bf7a99769439cf
                 git ls-remote origin refs/heads/main = 95bb7392d2fb4065a27ea931b1bf7a99769439cf
```

### I1 evidence

```
tools/verify_vendor.py   7a61aee3c330d59d674704b89fa8a69f3e4e2d7a2aad32debf9943632bf53445   5154
VENDOR_VERIFY PASS       vendor/eve-mcp == eve-mcp-v1 tree cbdcd191..., inventory 18/18,
                         manifest record_sha256 dfedb266ad1bb7a3e7af257eb9dd761445efe328a66dee46cb2a1b74ff18128d
vendored adapter tests   88 passed (.venv, Python 3.11, requirements.lock.txt of eve-mcp v1)
```

### I2 evidence (all under evidence\i2\ in commit a22d5e5)

```
I2_CLOSURE_2026-09-30.json        d1148a6b8a29a27d2396d75b00704c512a4102746ea19217369fe2732daa1825   7328
  record_sha256                   be1fb1fd312ba34ffb4e98fc6a347b6e59efc1350e13a1200d6659849b01a700
ACCEPTANCE_2026-09-30T143617Z.json d9fb10ddfc5fea6de4224959c3399ea133cae5f74449f6da9bbf705bd0711833   9430
REMOTE_PROBE_20260930T144452Z.json 9bfbbe0aaecbc175536fc8398588818bc003c34705468e4adf1103da3a4e1d01   1368
SUITE_VPS_20260930T142655Z.json   d62871df848232ec8969f32d23e3b64c312e472563397180eb8fc73fc105f7b4   2470
```

The closure record carries the full inventory (12 evidence files) and the instrument hashes.
What the gates established, as recorded there:

```
hosted backend     VPS /opt/eva-demo: EVE eve-core-v1 clone on 127.0.0.1:8012, EVE MCP v1 on 127.0.0.1:8765
public surface     ONLY https://grc.eveverified.com/eva/mcp, bearer gate in nginx
                   no-token 401 / wrong-token 401 / correct token + MCP initialize 200 / existing GRC page 200
                   8012 and 8765 not reachable from the internet (tested from the workstation)
local acceptance   PHASE1_ACCEPTANCE_PASS: CASE_A allow EVE-PAR-LOCAL-000001, CASE_B escalate -000002, VALID
remote probe       REMOTE_PROBE_PASS through the public surface: CASE_A allow -000003, CASE_B escalate -000004
VPS suite          SUITE_QUALIFIED_PASS 1283 passed / 10 environment-bound failures (H6 trusted-git
                   companion absent on Linux). NOT a full pass. The full accepted regression for tree
                   a698922c... remains 1293/1293 on the workstation runtime.
non-interference   existing GRC and its 11 pm2 processes unchanged (snapshots before == after)
```

---

## 3. I3 — NOT STARTED

```
authorised so far   read-only AWS discovery only (OWNER_DECISION 2026-09-30)
measured            AWS CLI not installed on the workstation
                    PyPI listing only (nothing installed): strands-agents 1.57.1, boto3 1.43.105
owner-reported      no AWS credentials on the workstation (OWNER_REPORTED 2026-09-30)
blocker             AWS discovery cannot run until credentials exist; creating them is an owner
                    account action outside the discovery GO
not established     Bedrock regions, accessible models, model id, invocation entitlement, quotas
```

Nothing in this track implements Strands, Bedrock, the deterministic gate, an Alexa+-style
experience or any agent behaviour. None of these exists as a fact here.

---

## 4. OWNER DECISIONS RECORDED 2026-09-30

```
I1 CLOSED; I2 CLOSED; I3 NOT_STARTED
the pointer deviation in section 5 is accepted; Git history is not rewritten
test-only httpx==0.28.1 in the VPS demo venv (GRC's 18 runtime packages unchanged)
VPS regression gate = qualified 1283/10 (decision A), never reported as a full pass
this track is self-contained: its existence and its dependency on EVE do not cause an Atlas
  mutation (ATLAS_PROJECT_BOUNDARY_FINDING accepted; P2/P3 not performed)
```

---

## 5. DEVIATIONS, RECORDED — NOT CORRECTED

```
POINTER_COMMIT_MERGED
  The standalone I1 pointer commit was never made; the I1 and I2 pointer states landed together
  in 95bb7392d2fb4065a27ea931b1bf7a99769439cf. Accepted by the owner; history not rewritten.

NO_DATED_HANDOVER_BEFORE_THIS_ONE
  The pointer moved twice without a dated handover, contrary to this track's own protocol.
  This file is the first dated handover.

INSTRUMENT_REPORTED_OK_ON_MISMATCH
  The first nginx step printed NGINX_OK on 404/404 (expected 401). Diagnosed as an nginx reload
  race; the instrument now fails hard on any mismatch. Detail in I2_CLOSURE deviations.
```

---

## 6. SEPARATE, NOT PART OF THIS TRACK

```
SECURITY   The pre-existing X-Trinity-Key and X-Ctrl-Energy-Key (api.eveverified.com) were exposed
           in terminal/chat output on 2026-09-30 and are classified COMPROMISED. Rotation is a
           separate owner-authorised act. Values are never reproduced.
```

---

## 7. NON-CLAIMS

```
this handover asserts no current state; it points at state measured on 2026-09-30
it establishes no accepted EVE state; EVE MCP v1 and EVA are not members of any ACCEPTED_BASELINE
EVE installation identity on the VPS remains OPERATOR_DECLARED
no I3 capability exists
```
