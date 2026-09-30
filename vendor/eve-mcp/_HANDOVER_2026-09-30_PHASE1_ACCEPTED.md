# 051_eve_mcp -- HANDOVER 2026-09-30 -- PHASE 1 ACCEPTED (immutable snapshot)

```
NAVIGATION ONLY. NOT AUTHORITY. Authority = the self-hashed records named below.
Written before _HANDOVER_CURRENT.md was moved to this state (RECORDING PROTOCOL 4).
```

## Result

PHASE 1 (EVE MCP v1) LIVE ACCEPTANCE PASSED against the real pinned EVE, 2026-09-30 12:19-12:20Z.

```
acceptance record   evidence\ACCEPTANCE_2026-09-30T122051Z.json
                    record_sha256 79698509e0d2351e464e424a7b4266ffeb5a80c42590815a2fe387f0a4352635 (independently recomputed: MATCH)
                    whole-file sha256 f1d1ded2fa3bf848429f5fc486b444cf848bffb29d738f6d615b782871f54781, 9964 B, no token inside
scenario build      evidence\SCENARIO_BUILD_2026-09-30T120122Z.json  record_sha256 034c48c3...  mode PRINT_ONLY
                    evidence\SCENARIO_BUILD_2026-09-30T120148Z.json  record_sha256 f8443e98...  mode SAVE
```

## Pinned EVE (measured by the harness from the clone's git objects)

```
clone            D:\EVE_DEMO\eve-core-v1   HEAD ffe118c326e3d4ec4b194ddea0ba6c8d09d78f27   tree a698922c9fd740c4b114e572a626380abf1590a4
full suite       1293 passed, 1 warning, 100.95 s (venv_gpu, run BY the harness inside the clone, exit 0)
runtime store    D:\EVE_DEMO\eve_store (external; the EVE process env is OPERATOR_ASSERTED)
binding          EVE 127.0.0.1:8002, MCP 127.0.0.1:8765/mcp (loopback only)
identity claim   OPERATOR_DECLARED -- EVE has no self-attesting identity endpoint
```

## Case A / Case B (real EVE engine, real policy evaluation, real sealed records)

```
policy           eve-mcp-demo-policy-v1  policy_content_sha256 e7a23e8c448ccff96f54ca7a449908e5707a2df5e7f37afcc61d712a285867aa
                 registry file sha256 7d9cd6a72ff48673c58ed0973e228be6a73f87af0d9fb1f03176f3036a39609c
scenarios file   sha256 98bc8a5e7c9cf045afa7332fa6588fe5bee5dac9500b6708bc02eb0898d4a803

CASE_A  chain EVE-MCP-DEMO-A-2026-001  content_hash 4a972db7121f635494887510278304b50e6c12498a7aead4f8a2d8ded27d8402
        engine: SUPPORTED / ACTION_CHAIN_SUPPORTED / gaps []      chain seal EVE-CHAIN-LOCAL-000001 VALID
        MCP: HTTP 200, verified_chain_outcome ACTION_CHAIN_SUPPORTED, customer_policy_outcome allow (EMP-ALLOW-001)
        record EVE-PAR-LOCAL-000003  par-1.2  verify VALID  (all five correspondence predicates True)

CASE_B  chain EVE-MCP-DEMO-B-2026-001  content_hash 3246e4631f0fa87778ab55411a583d5dbb10048033f30057b5f1ce2e45308453
        engine: PARTIAL / HUMAN_REVIEW_REQUIRED / gaps [MISSING_EVIDENCE]   chain seal EVE-CHAIN-LOCAL-000002 VALID
        MCP: HTTP 200, verified_chain_outcome HUMAN_REVIEW_REQUIRED, customer_policy_outcome escalate (EMP-ESCALATE-001)
        record EVE-PAR-LOCAL-000004  par-1.2  verify VALID  (all five correspondence predicates True)

correspondence predicates (both cases): record_id == X-EVE-Record-Id; record.chain_id == eve.chain_id;
record.chain_content_hash == chain content_hash; record.policy_content_hash == MCP policy_content_sha256;
record.result deep-equals the MCP `eve` envelope.

live security checks: caller policy_config refused by MCP before any EVE call; unknown chain -> EVE 404
envelope passed through with eve_record_id null; EVE direct 422/404 paths carry no record header.
MCP server eve-mcp 0.1.0, protocol 2025-11-25, tools ['eve_pre_action'].
```

## Known artefacts of the run (not defects)

```
EVE-PAR-LOCAL-000001 / 000002  minted by the FIRST harness run (2026-09-30 ~12:1xZ), which aborted at the
                               operator-verification step because the read token had been set to a non-ASCII
                               placeholder. Both are real evaluated records in D:\EVE_DEMO\eve_store, never
                               verified by a harness and referenced by no evidence record. Left in place.
                               Fix applied afterwards: harness validates the token at step 0, before minting.
```

## Deliverable identities at acceptance (sha256, bytes)

```
_HANDOVER_CURRENT.md                    (rewritten after this snapshot)
README.md                               5f06f15031e86e1a8d23844626102556aec8a1a0ee46acbfe7d2caa2ff7d1018   8812
pyproject.toml                          0b7eee1cd5dceef0f753f75573dbedcb1f9e192ec50c09aceca0844904420f94    535
eve_mcp/__init__.py                     74e2cc4781ed454c78c63cb80d2b932507ea76144a6cff2947099126ce0225c9    342
eve_mcp/core.py                         07b3acad160d67797166d355b0f88b4a8c25a5a0c4549bb803874c1b8c4242f6  21974
eve_mcp/server.py                       c46556f0fb072066de98118785aafc8525ab72d06c7885d0aaad5805900e90d9   9501
policies/policy_registry_v1.json        7d9cd6a72ff48673c58ed0973e228be6a73f87af0d9fb1f03176f3036a39609c   2163
scenarios/scenarios_v1.json             98bc8a5e7c9cf045afa7332fa6588fe5bee5dac9500b6708bc02eb0898d4a803   6574
scenarios/build_scenario_chains.py      d11c248409609e7a29b82ad34db6a26b23989e1723025005796def8696ce8f4b  15431  (fix: steps tuple passed explicitly)
tests/test_core.py                      bc7503f733ee676f16251b8fddcdb97a60e6732c494dfd9b2f9a985fa895874c  16228
tests/test_wire.py                      a07a18f3b050aa6e14177c57408967a97200d1cf456908f85d89f9fa91246022  13358  (fix: 5 s budget for Windows SYN retry)
acceptance/run_acceptance.py            0c3732ba05143ccc57e72846904a7fc21a84c63b4d5895fa366ea765ab2d61cb  15634  (fix: token validated at step 0)
tests                                   88 passed on Windows (.venv, Python 3.11) and 88 passed on Linux (sandbox)
dependencies                            mcp 1.30.0, httpx 0.28.1, uvicorn 0.54.0, starlette 1.7.0, pytest 9.1.1
```

## Not claimed

EVE attestation of the installation identity; MCP protocol 2026-07-28; any auth on the MCP endpoint;
that the synthetic chains describe real events (they are declared demo data; the evaluation records are real);
Bridge anchoring of any record; that eve-verified-grc was touched (it was not).
