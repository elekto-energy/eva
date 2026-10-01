# EVA Business Agent v0.1 -- gap analysis (read-only, 2026-10-01)

Goal: the smallest product a real company can pay for and use in one real workflow, in which
EVA can propose a real consequential action but cannot get past the frozen EVE MCP v1 boundary.

Basis: EVA repository at commit c714e22322fa5478004a486963b73114f03b4de4. Read-only analysis:
no code, configuration, EVE core or EVE MCP was changed.

Owner decisions recorded on this analysis (2026-10-01):
- D1 = YES: the supplier-risk workflow is the first workflow, used as the commercial reference
  implementation of the control pattern (not as a "supplier-risk agent" product).
- No named pilot customer is required before the product core is built. A customer is required
  before the customer-specific connector and before any production deployment.
- F4 is an explicit architecture/product limitation of v0.1 (section C); it is not to be solved
  inside v0.1 by changing the frozen gate or the frozen EVE.

---

## A. Measured facts that shape the analysis

| Source | sha256 |
|---|---|
| eva/gate.py (frozen I3A boundary) | 8eeff78772a97508cbf2ee8acfdbbb22c0c4ad08b7677063f3b9e9a58cbc7ed8 |
| eva/tools.py (frozen I3A boundary) | 70e88f7138ec02f099d0b4e79ebc81909febe63810e99be4a5f68ee0d5e84ac3 |
| eva/config.py | 92618b2a9467eddf2ec91f4ba77f9b6f7e1f720642db33c640b7653ffcbbb3aa |
| vendor/eve-mcp/README.md | b817356caf599ffe58d57a2d8e661d0d25bca082770ff6a3a5cce703fcc4b30f |
| vendor/eve-mcp/scenarios/build_scenario_chains.py | d11c248409609e7a29b82ad34db6a26b23989e1723025005796def8696ce8f4b |

F1 -- The frozen gate is bound to one workflow. gate.py requires the argument set exactly
{supplier_id, risk_status} and resolves the chain by supplier_id; config.ALLOWED_TOOLS and
CONSEQUENTIAL_TOOLS contain only the supplier tools. Any other workflow needs a governed change of
gate.py and a full re-run of the I3A adversarial suite. The supplier-risk workflow uses the
boundary unchanged.

F2 -- The boundary can be reused without change. build_tools(store, register, ...) accepts the
register by interface (get, set_risk_status) and EveGate(..., chain_map=...) accepts the chain
map as a parameter. A real connector and a customer chain map can be injected without changing
any of the five frozen files.

F3 -- EVE MCP v1 does not construct chains. Its README states that it "does not construct chains,
does not collect or judge evidence". The demo chains were built by the operator instrument
build_scenario_chains.py, which runs EVE's own engine over DECLARED data (governance facts plus
raw evidence per step), never overwrites a chain, writes only to the external store, and has an
equivalence gate against resolve(). There is no path today for a customer's evidence into EVE.
This is the largest single gap.

F4 -- A chain authorises a class of action, not a value. requested_risk_status travels in
action_context, which EVE echoes and never treats as evidence. See section C.

F5 -- The frozen tools.py consumes the authorization before writing. If
register.set_risk_status raises, no entry is added to the execution log, so a failed or
ambiguous write against a real system leaves no EVA record of its own. This must be handled in
the connector layer, which is possible without changing frozen files.

---

## B. Core flow: present state and gaps

| Link | Today | Gap |
|---|---|---|
| Real connector / tool | JSON file (SupplierRegister) | Thin adapter to the customer's system implementing get / set_risk_status, read-after-write, own attempt log, ambiguous outcome reported as UNKNOWN and never as success (Pilot Adapter) |
| EVE verification | Works, against synthetic chains only | Chain-intake instrument for customer evidence (F3); new chain id per evidence version; never overwrite; everything labelled customer- or operator-declared (v0.1 core) |
| Deterministic authorization | Frozen; 49 tests; A/B proven live | None, for the supplier-risk workflow |
| Execution | Single-use authorization bound to exact arguments | Covered by the connector row |
| Human review | Escalate = blocked, end of flow | Rule: an approval inside EVA never becomes an execution. Minimum: review queue (proposal, EVE record, reason); the human acts in their own system; EVA records "handled by human". Later: new evidence -> new chain -> EVE re-evaluates (v0.1 core) |
| Evidence / audit | Local records in evidence/ and runs/; EVE records on the VPS | Durable append-only audit log plus an export bundle per action: proposal, EVE answer and record id, authorization, execution, connector read-back (v0.1 core) |

---

## C. Explicit limitation of v0.1 (F4)

What EVE verifies in v0.1: whether this class of consequential action is supported by the
customer-declared evidence chain under the operator-owned policy -- for example, "this agent may
change the risk status of SUP-001".

What EVE does not verify in v0.1: that the evidence supports the exact proposed value -- for
example, "the evidence supports changing SUP-001 from MEDIUM to HIGH".

What EVA adds: the exact proposed action is bound before execution. The deterministic
authorization covers (tool_use_id, tool, exact arguments), so the model cannot change the value
after EVE has answered; any change voids the authorization.

Product contract for v0.1, to be stated as written:

    EVE verifies whether this class of action is supported.
    EVA binds the exact proposed action before execution.

Future architecture question (not v0.1, not inside the frozen EVE): verification of
evidence -> proposition -> exact consequential action, so that EVE itself establishes that the
evidence supports the specific change. This requires its own design and governed change.

Other claim boundaries for v0.1: a valid seal proves record integrity, never the truth of
customer-declared evidence; seals are local, not Bridge-anchored; the EVE identity is
OPERATOR_DECLARED, not self-attested.

---

## D. Operations and surrounding needs

| Area | Today | v0.1 core | Pilot Adapter | Later |
|---|---|---|---|---|
| Deployment | EVE shared on the VPS (demo store); EVA local | Demo EVE instance with synthetic, labelled reference data | Own EVE instance per customer (external store, services, nginx path, bearer, backup) reusing the I2 scripts; EVA runs at the customer | Own VPS per customer; multi-tenant |
| Secrets | SecretFile; bearer outside the repo | Same pattern for model keys; nothing logged | Connector credentials and the customer bearer in the same pattern | Rotation routine; vault |
| Customer configuration | Hard-wired demo (chain_map.json, POLICY_REF) | Chain map and policy_ref loaded from a customer configuration file, validated fail-closed, injected (F2); frozen files and the frozen-boundary test untouched | The customer's own file | Configuration UI |
| Users / permissions | Localhost web, no login | One named operator per installation, recorded in every record | Same | Login and roles (propose / review); SSO |
| Model | Nova blocked; scripted proposer | Model selected by configuration; one provider outside AWS; always labelled; no silent fallback; Nova added later unchanged | Customer's choice of provider | Several providers; routing |
| Errors / recovery | Fail-closed gate; in-memory authorization | Restart never loses the audit log | Ambiguous writes reported; backup of the customer's EVE store (sealed records are the customer's audit evidence); runbook | Health monitoring; high availability |
| Agreements | None | -- | Pilot agreement; data processing agreement if personal data occurs | -- |

Not in v0.1: VHR, multi-agent chains, offline/resync, OpsWatch integration, exposing H7/G3 through
MCP, any change to EVE core or EVE MCP, workflow builder, connector marketplace, GRC platform.

---

## V0.1_BUILD_PLAN

Estimates are rough working days for one developer with Claude; they are estimates, not
measurements.

### EVA Business Agent v0.1 -- product core (no customer required)

| Step | Content | Estimate | Gate |
|---|---|---|---|
| 1 | Chain-intake instrument: generalise build_scenario_chains.py to a customer-neutral evidence format; keep the equivalence gate; never overwrite; new chain id per evidence version; operator side, no core change; exercised on a synthetic, labelled reference dataset | 3-5 d | GO when chains built from the evidence format yield the same verdict as resolve() |
| 4 | Customer configuration: chain map and policy_ref from a configuration file, injected, fail-closed | 1-2 d | GO when the frozen-boundary test is still green |
| 5 | Model selection by configuration: one provider outside AWS, labelled, no silent fallback | 1-2 d | Needs D3. GO after one live call through the same boundary |
| 6 | Review queue (human acts in their own system) and durable audit log with export bundle | 3-4 d | Needs D4. GO when an exported action verifies standalone |
| 7a | Installable product core: install script, secret placement, service, health check, runbook | 1-2 d | GO after installation from a clean machine |

Product core total: about 9-15 working days.

### EVA Pilot Adapter -- only when a customer exists

| Step | Content | Estimate | Gate |
|---|---|---|---|
| 2 | Own EVE instance for the customer, including backup | 2-3 d | GO after remote probe (allow / escalate) and a backup restore |
| 3 | Thin connector to the customer's system (SAP, Dynamics, own database, API, supplier system ...) with read-after-write, attempt log, ambiguous outcome | 3-5 d (depends on the system) | GO after adversarial tests: write failure, timeout, replay, wrong value |
| 7b | Customer installation and customer-specific runbook | 1 d | GO after installation in the customer environment |
| 8 | Acceptance: full I3A suite, connector tests, live A/B in the customer sandbox | 2-3 d | STOP before production; owner decision |

Pilot Adapter total: about 8-12 working days per customer.

### Decisions still open

- D2 Topology for pilots (EVA at the customer and an own EVE instance hosted by us, or everything
  at the customer) -- needed before step 2.
- D3 Model provider outside AWS -- needed before step 5.
- D4 Human-review semantics ("the human acts, EVA records" as minimum, or "new evidence -> new
  chain -> re-evaluation") -- needed before step 6.

The Amazon submission (deadline 2026-10-23) runs in parallel; its packaging is not part of this
plan.
