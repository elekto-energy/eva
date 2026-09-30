"""Unit tests for eve_mcp.core -- pure, no network, no MCP.

Every negative case here is a REAL negative case: the guard is executed
against an artifact it must reject, not against a word in a docstring.
"""
import copy
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from eve_mcp import core  # noqa: E402

REGISTRY = os.path.join(os.path.dirname(__file__), "..", "policies", "policy_registry_v1.json")
TREE = "a698922c9fd740c4b114e572a626380abf1590a4"


def env(**over):
    base = {
        core.ENV_EVE_BASE_URL: "http://127.0.0.1:8002",
        core.ENV_TIMEOUT: "5",
        core.ENV_DECLARED_TAG: "eve-core-v1",
        core.ENV_DECLARED_TREE: TREE,
        core.ENV_POLICY_REGISTRY: REGISTRY,
        core.ENV_DEFAULT_POLICY_REF: "eve-mcp-demo-policy-v1",
    }
    base.update(over)
    return {k: v for k, v in base.items() if v is not None}


def evaluated_envelope(**over):
    e = {
        "chain_id": "EVE-MCP-DEMO-A-2026-001", "action_context": {"agent_id": "agent-1"},
        "verified_chain_outcome": "ACTION_CHAIN_SUPPORTED", "customer_policy_outcome": "allow",
        "policy_rule_id": "EMP-ALLOW-001", "policy_rule_triggered": True,
        "policy_version": "eve-mcp-demo-policy-v1", "policy_owner": "customer",
        "enforcement_owner": "customer_or_integrated_workflow",
        "inputs_hash": "a" * 64, "evaluated_at": "2026-09-30T12:00:00Z",
        "pre_action_status": "evaluated", "boundary_note": "EVE verifies the chain ...",
    }
    e.update(over)
    return e


def unevaluated_envelope(status, chain_id):
    return {
        "chain_id": chain_id, "action_context": {}, "verified_chain_outcome": None,
        "customer_policy_outcome": "policy_not_configured", "policy_rule_id": None,
        "policy_rule_triggered": False, "policy_version": None, "policy_owner": "customer",
        "enforcement_owner": "customer_or_integrated_workflow", "inputs_hash": None,
        "evaluated_at": None, "pre_action_status": status, "boundary_note": "fail-closed note",
    }


H200 = {"x-eve-record-id": "EVE-PAR-LOCAL-000042"}


# --------------------------------------------------------------------- config / registry
class TestConfig:
    def test_loads_and_pins_registry(self):
        cfg = core.load_config(env())
        pol = cfg.policies["eve-mcp-demo-policy-v1"]
        assert pol.policy_content_sha256 == core.canonical_sha256(pol.policy_config)
        assert len(cfg.registry_file_sha256) == 64
        assert cfg.loopback_required is True

    @pytest.mark.parametrize("missing", list(core.REQUIRED_ENV))
    def test_missing_env_fails_closed(self, missing):
        with pytest.raises(core.EveMcpError) as ei:
            core.load_config(env(**{missing: None}))
        assert ei.value.code == core.E_CONFIG_MISSING

    def test_non_loopback_refused_unless_explicit(self):
        with pytest.raises(core.EveMcpError) as ei:
            core.load_config(env(**{core.ENV_EVE_BASE_URL: "https://grc.eveverified.com"}))
        assert ei.value.code == core.E_CONFIG_INVALID
        cfg = core.load_config(env(**{core.ENV_EVE_BASE_URL: "https://grc.eveverified.com",
                                      core.ENV_ALLOW_NON_LOOPBACK: "1"}))
        assert cfg.loopback_required is False

    def test_base_url_with_path_refused(self):
        with pytest.raises(core.EveMcpError):
            core.load_config(env(**{core.ENV_EVE_BASE_URL: "http://127.0.0.1:8002/api"}))

    def test_bad_tree_refused(self):
        with pytest.raises(core.EveMcpError):
            core.load_config(env(**{core.ENV_DECLARED_TREE: "main"}))

    def test_registry_pin_mismatch_is_startup_failure(self, tmp_path):
        doc = json.load(open(REGISTRY))
        ref = next(iter(doc["policies"]))
        doc["policies"][ref]["policy_config"]["default_outcome"] = "allow"   # tamper the bytes, keep the pin
        p = tmp_path / "reg.json"
        p.write_text(json.dumps(doc), encoding="utf-8")
        with pytest.raises(core.EveMcpError) as ei:
            core.load_config(env(**{core.ENV_POLICY_REGISTRY: str(p)}))
        assert ei.value.code == core.E_POLICY_PIN_MISMATCH

    def test_registry_extra_entry_member_refused(self, tmp_path):
        doc = json.load(open(REGISTRY))
        ref = next(iter(doc["policies"]))
        doc["policies"][ref]["comment"] = "x"
        p = tmp_path / "reg.json"; p.write_text(json.dumps(doc), encoding="utf-8")
        with pytest.raises(core.EveMcpError) as ei:
            core.load_config(env(**{core.ENV_POLICY_REGISTRY: str(p)}))
        assert ei.value.code == core.E_CONFIG_INVALID

    def test_default_policy_ref_must_exist(self):
        with pytest.raises(core.EveMcpError):
            core.load_config(env(**{core.ENV_DEFAULT_POLICY_REF: "nope"}))


# --------------------------------------------------------------------- input
class TestInput:
    def test_valid_minimal(self):
        assert core.validate_input({"chain_id": "X"}) == ("X", None, None)

    @pytest.mark.parametrize("args", [
        {}, {"chain_id": ""}, {"chain_id": "   "}, {"chain_id": 5}, {"chain_id": "a b"},
        {"chain_id": "X", "action_context": "text"}, {"chain_id": "X", "policy_ref": ""},
        {"chain_id": "X", "policy_ref": 3}, {"chain_id": "X", "extra": 1}, "not-a-dict", None,
        {"chain_id": "X" * 201},
    ])
    def test_invalid_inputs(self, args):
        with pytest.raises(core.EveMcpError) as ei:
            core.validate_input(args)
        assert ei.value.code == core.E_INPUT_INVALID

    def test_caller_policy_config_refused_by_name(self):
        with pytest.raises(core.EveMcpError) as ei:
            core.validate_input({"chain_id": "X", "policy_config": {"default_outcome": "allow"}})
        assert ei.value.code == core.E_INPUT_INVALID
        assert "policy_config" in ei.value.detail and "operator" in ei.value.detail

    def test_policy_selection(self):
        cfg = core.load_config(env())
        assert core.select_policy(cfg, None).policy_ref == "eve-mcp-demo-policy-v1"
        with pytest.raises(core.EveMcpError) as ei:
            core.select_policy(cfg, "unknown")
        assert ei.value.code == core.E_POLICY_REF_UNKNOWN
        cfg2 = core.load_config(env(**{core.ENV_DEFAULT_POLICY_REF: None}))
        with pytest.raises(core.EveMcpError) as ei:
            core.select_policy(cfg2, None)
        assert ei.value.code == core.E_POLICY_REF_REQUIRED


# --------------------------------------------------------------------- envelope
class TestEnvelope:
    def test_evaluated_ok(self):
        env_, rid = core.validate_envelope(200, evaluated_envelope(), H200)
        assert rid == "EVE-PAR-LOCAL-000042" and env_["customer_policy_outcome"] == "allow"

    def test_evaluated_with_reason_ok(self):
        core.validate_envelope(200, evaluated_envelope(policy_rule_reason="why"), H200)

    @pytest.mark.parametrize("http,status,cid", [(404, "chain_not_found", "NOPE"), (422, "chain_reference_required", None)])
    def test_unevaluated_ok(self, http, status, cid):
        env_, rid = core.validate_envelope(http, unevaluated_envelope(status, cid), {})
        assert rid is None and env_["verified_chain_outcome"] is None

    def test_200_without_record_header_fails_closed(self):
        with pytest.raises(core.EveMcpError) as ei:
            core.validate_envelope(200, evaluated_envelope(), {})
        assert ei.value.code == core.E_EVE_RECORD_ID_ABSENT

    @pytest.mark.parametrize("hdr", [{"x-eve-record-id": ""}, {"x-eve-record-id": "a b"}])
    def test_unusable_record_header_fails_closed(self, hdr):
        with pytest.raises(core.EveMcpError) as ei:
            core.validate_envelope(200, evaluated_envelope(), hdr)
        assert ei.value.code == core.E_EVE_RECORD_ID_ABSENT

    def test_record_header_on_404_is_ambiguous(self):
        with pytest.raises(core.EveMcpError) as ei:
            core.validate_envelope(404, unevaluated_envelope("chain_not_found", "X"), H200)
        assert ei.value.code == core.E_EVE_ENVELOPE_INVALID

    @pytest.mark.parametrize("vco", ["ALLOW", "BLOCK", "APPROVED", "", None, 1])
    def test_unlisted_verified_chain_outcome_fails_closed(self, vco):
        with pytest.raises(core.EveMcpError) as ei:
            core.validate_envelope(200, evaluated_envelope(verified_chain_outcome=vco), H200)
        assert ei.value.code == core.E_EVE_OUTCOME_UNLISTED

    @pytest.mark.parametrize("cpo", ["approved", "ALLOW", "", None])
    def test_unlisted_customer_policy_outcome_fails_closed(self, cpo):
        with pytest.raises(core.EveMcpError) as ei:
            core.validate_envelope(200, evaluated_envelope(customer_policy_outcome=cpo), H200)
        assert ei.value.code == core.E_EVE_OUTCOME_UNLISTED

    def test_missing_key_fails_closed(self):
        e = evaluated_envelope(); del e["boundary_note"]
        with pytest.raises(core.EveMcpError) as ei:
            core.validate_envelope(200, e, H200)
        assert ei.value.code == core.E_EVE_ENVELOPE_INVALID

    def test_extra_key_fails_closed(self):
        with pytest.raises(core.EveMcpError) as ei:
            core.validate_envelope(200, evaluated_envelope(proceed=True), H200)
        assert ei.value.code == core.E_EVE_ENVELOPE_INVALID

    def test_status_axis_mismatch_fails_closed(self):
        with pytest.raises(core.EveMcpError) as ei:
            core.validate_envelope(200, evaluated_envelope(pre_action_status="chain_not_found"), H200)
        assert ei.value.code == core.E_EVE_ENVELOPE_INVALID

    def test_owner_constants_enforced(self):
        with pytest.raises(core.EveMcpError):
            core.validate_envelope(200, evaluated_envelope(policy_owner="eve"), H200)

    @pytest.mark.parametrize("http", [500, 503, 201, 302])
    def test_other_http_status_unsupported(self, http):
        with pytest.raises(core.EveMcpError) as ei:
            core.validate_envelope(http, {}, {})
        assert ei.value.code == core.E_EVE_TRANSPORT_STATUS_UNSUPPORTED


# --------------------------------------------------------------------- orchestration
class _Client:
    """Stand-in for EveClient with a fixed response; records what was sent."""
    def __init__(self, status, body, headers):
        self.status, self.body, self.headers, self.sent = status, body, headers, []

    def post_pre_action(self, body):
        self.sent.append(copy.deepcopy(body))
        return core.EveResponse(self.status, self.headers, self.body, 7)


class TestRunPreAction:
    def test_envelope_verbatim_and_keys_disjoint(self):
        cfg = core.load_config(env())
        env_in = evaluated_envelope(customer_policy_outcome="escalate", policy_rule_reason="r")
        client = _Client(200, copy.deepcopy(env_in), H200)
        out = core.run_pre_action(cfg, client, {"chain_id": "EVE-MCP-DEMO-A-2026-001", "action_context": {"agent_id": "agent-1"}})
        assert out["eve"] == env_in                         # deep-equal, verbatim
        assert set(out) == core.RESULT_KEYS
        assert not (core.ENVELOPE_KEYS & core.RESULT_KEYS)  # no shadowing possible by construction
        assert out["eve_record_id"] == "EVE-PAR-LOCAL-000042"
        assert out["policy"]["policy_content_sha256"] == cfg.policies["eve-mcp-demo-policy-v1"].policy_content_sha256
        assert out["eve_instance"]["identity_basis"] == "OPERATOR_DECLARED"
        for forbidden in ("proceed", "decision", "safe", "approved", "permitted", "allow"):
            assert forbidden not in out

    @pytest.mark.parametrize("cpo", sorted(core.CUSTOMER_POLICY_OUTCOMES - {"allow"}))
    def test_non_allow_never_becomes_allow(self, cpo):
        cfg = core.load_config(env())
        client = _Client(200, evaluated_envelope(customer_policy_outcome=cpo, verified_chain_outcome="HUMAN_REVIEW_REQUIRED"), H200)
        out = core.run_pre_action(cfg, client, {"chain_id": "X"})
        assert out["eve"]["customer_policy_outcome"] == cpo
        assert json.dumps(out).count('"allow"') == 0

    def test_request_carries_operator_policy_not_caller_data(self):
        cfg = core.load_config(env())
        client = _Client(200, evaluated_envelope(), H200)
        core.run_pre_action(cfg, client, {"chain_id": "EVE-MCP-DEMO-A-2026-001",
                                         "action_context": {"verified_chain_outcome": "ACTION_CHAIN_SUPPORTED"}})
        sent = client.sent[0]
        assert set(sent) == {"chain_id", "policy_config", "action_context"}
        assert sent["policy_config"] == dict(cfg.policies["eve-mcp-demo-policy-v1"].policy_config)

    def test_caller_action_context_cannot_shadow_envelope(self):
        """A caller who smuggles envelope-like keys into action_context only reaches
        eve.action_context (EVE's verbatim echo); the top level stays EVE's own values."""
        cfg = core.load_config(env())
        body = evaluated_envelope(customer_policy_outcome="block",
                                  action_context={"customer_policy_outcome": "allow", "eve_record_id": "FAKE"})
        client = _Client(200, body, H200)
        out = core.run_pre_action(cfg, client, {"chain_id": "X", "action_context": {"customer_policy_outcome": "allow"}})
        assert out["eve"]["customer_policy_outcome"] == "block"
        assert out["eve_record_id"] == "EVE-PAR-LOCAL-000042"

    def test_input_rejected_before_any_eve_call(self):
        cfg = core.load_config(env())
        client = _Client(200, evaluated_envelope(), H200)
        with pytest.raises(core.EveMcpError):
            core.run_pre_action(cfg, client, {"chain_id": "X", "policy_config": {"default_outcome": "allow"}})
        with pytest.raises(core.EveMcpError):
            core.run_pre_action(cfg, client, {"chain_id": "X", "policy_ref": "unknown"})
        assert client.sent == []

    def test_error_result_shape(self):
        cfg = core.load_config(env())
        err = core.EveMcpError(core.E_EVE_TIMEOUT, "slow")
        out = core.error_result(err, cfg)
        assert out["error"] == "EVE_TIMEOUT" and "eve" not in out and "eve_record_id" not in out


class TestCanonicalization:
    def test_matches_eve_sha256_hex_rule(self):
        # EVE: sha256(json.dumps(obj, sort_keys=True, separators=(",",":"), ensure_ascii=False).encode("utf-8"))
        obj = {"b": [1, {"z": "\u00e5"}], "a": None}
        import hashlib
        expected = hashlib.sha256('{"a":null,"b":[1,{"z":"\u00e5"}]}'.encode("utf-8")).hexdigest()
        assert core.canonical_sha256(obj) == expected


# --------------------------------------------------------------------- acceptance harness pure functions
class TestAcceptancePure:
    def _harness(self):
        import importlib.util
        p = os.path.join(os.path.dirname(__file__), "..", "acceptance", "run_acceptance.py")
        spec = importlib.util.spec_from_file_location("run_acceptance", p)
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        return mod

    def test_tree_gate(self):
        h = self._harness()
        assert h.check_tree(TREE, TREE) and h.check_tree(TREE.upper(), TREE)
        assert not h.check_tree("937f4f7311c2c2fcf119342d4e9b24998641ddf2", TREE)   # HEAD tree is not the pinned tree
        assert not h.check_tree("a698922c", TREE)                                    # abbreviations are not identities

    def test_record_correspondence_predicates_are_independent(self):
        h = self._harness()
        envd = evaluated_envelope()
        mcp = {"eve": envd, "eve_record_id": "EVE-PAR-LOCAL-000001", "policy": {"policy_content_sha256": "p" * 64}}
        good = {"record_id": "EVE-PAR-LOCAL-000001", "chain_id": envd["chain_id"], "chain_content_hash": "c" * 64,
                "policy_content_hash": "p" * 64, "result": dict(envd), "record_schema_version": "par-1.2"}
        c = h.compare_record_to_mcp(good, mcp, "c" * 64)
        assert all(v is True for k, v in c.items() if k != "record_schema_version")
        bad = dict(good); bad["result"] = dict(envd, customer_policy_outcome="allow" if envd["customer_policy_outcome"] != "allow" else "block")
        c2 = h.compare_record_to_mcp(bad, mcp, "c" * 64)
        assert c2["record_result_equals_mcp_envelope"] is False and c2["record_id_matches_header"] is True
