# EVA -- Friction Log (Build, Ship, Shape: Amazon Developer Hackathon)

Developer-experience friction observed while building EVA (Evidence Verification Agent, powered by EVE)
on the Strands Agents SDK and Amazon Bedrock. One entry per observed event. Every entry names the
evidence it rests on; where a statement is not backed by an EVA evidence record, its basis is labelled.

Basis labels:
- MEASURED       -- recorded by an EVA instrument; the record is named with its sha256
- OWNER_OBSERVED -- read by the account owner in the AWS console; no EVA record exists for it
- NOT_ESTABLISHED -- not determined; stated so that it is not mistaken for a finding

Evidence paths are relative to the repository root unless they start with `D:\` (tools kept outside the
repository on the developer workstation).

---

## F-001 -- First Bedrock call blocked by account verification after IAM and model access looked ready

| Field | Entry |
|---|---|
| Date (UTC) | 2026-09-30, 17:48:39Z and 17:49:45Z |
| Task | Make the first Amazon Nova call (`amazon.nova-lite-v1:0`, `eu-north-1`) through Strands `BedrockModel` (ConverseStream) as the least-privilege IAM user `eva-runtime` |
| Expected | Having confirmed model access read-only beforehand, the first call returns a completion |
| Actual | `AccessDeniedException` on ConverseStream: "Your account is currently being verified. Verification normally takes less than 2 hours. Until your account is verified, you may not have access to this operation." |
| Severity | Critical for the live test: no Bedrock call is possible, so the agent cannot run on a real model |
| Workaround | None on the developer side. Wait for AWS account verification. Code, IAM identity and configuration were left unchanged. |
| Suggestion | Show the account-verification state in the Bedrock console and in the read-only model-access APIs. Before the first call, the discovery identity saw `amazon.nova-lite-v1:0` in `eu-north-1` as `authorizationStatus=AUTHORIZED`, `entitlementAvailability=AVAILABLE`, `regionAvailability=AVAILABLE`, agreement `AVAILABLE`. Nothing the developer could query indicated that runtime calls would be refused. |

Evidence (MEASURED):

```
evidence/i3b/RUNB_20260930T174839Z_proof.json   dbb6fdb3b32c98b90efdd363438362f0ff663750bea89275d441b47d00d2fd96  1577
evidence/i3b/RUNB_20260930T174945Z_proof.json   5e4da9b081fc582683bac7d54880629e6dc920a54a720a04a6f00088953cffbc  1577
D:\EVE11\tools\eva_aws_discovery\discovery_round2b.json
                                                0cb730324785d54cf1fca7815a4c6fec3e212dfa5e425505c87174281495386d  76087
  (model availability for amazon.nova-lite-v1:0 in eu-north-1 and eu-central-1, identity user/eva-discovery)
```

NOT_ESTABLISHED: when verification completed. The error text changed between 17:49:45Z and 17:57:26Z
(see F-002); no AWS notification is recorded here.

---

## F-002 -- Applied Bedrock quotas for Nova Lite were 0 while the AWS defaults are non-zero

| Field | Entry |
|---|---|
| Date (UTC) | 2026-09-30, from 17:57:26Z |
| Task | Retry the first Nova Lite call after the verification error stopped appearing |
| Expected | A completion, or a quota message consistent with the default quotas shown in Service Quotas |
| Actual | `ThrottlingException` on ConverseStream (after 4 automatic retries): "Too many tokens per day, please wait before trying again." -- although no call had ever succeeded, so no tokens had been consumed. In Service Quotas, the applied account-level values for Nova Lite in `eu-north-1` were 0 (default values non-zero) and marked "Not adjustable". |
| Severity | Critical for the live test: the model cannot be invoked; the quota cannot be raised through Service Quotas |
| Workaround | Support case to AWS asking for the default on-demand quotas to be applied. No model or region change was made. |
| Suggestion | (1) When an applied quota is 0, say so in the runtime error ("applied quota for this model is 0") instead of "Too many tokens per day, please wait", which suggests usage and time-based recovery. (2) If a new account's applied quotas are intentionally 0, show this next to the model-access status and offer a path to request them where the quota is marked "Not adjustable". |

Evidence (MEASURED -- the throttling responses):

```
evidence/i3b/RUNB_20260930T175726Z_proof.json   280df442349c0250cfeac5b95862e4e464bd342a4089ecd967c909513eb83978  1340
evidence/i3b/RUNB_20260930T180034Z_proof.json   2faee1094f4adddcb03bfd7eb8bc4f2b528c81eb7ee952b891b4325636698d01  1340
evidence/i3b/RUNB_20260930T180416Z_proof.json   42892fa3319f2d629e24f5198e08a4038d8637b0dd233fde06ee88675f649fc9  1340
```

OWNER_OBSERVED (Service Quotas console, Amazon Bedrock, `eu-north-1`; values as reported in the support case):

```
Quota                                                            Applied   AWS default
Model invocation max tokens per day for Amazon Nova Lite            0      5,760,000,000
On-demand model inference requests per minute, Amazon Nova Lite     0      200
On-demand model inference tokens per minute, Amazon Nova Lite       0      200,000
Cross-region model inference tokens per minute, Amazon Nova Lite    0      400,000
All four marked "Not adjustable".
CloudTrail ThrottlingException events for user/eva-runtime observed 18:17:39Z-18:19:01Z.
```

Scope limits:
- The EVA discovery instrument did not measure quotas (it calls no Service Quotas API). The quota values
  above are the owner's console reading, not an EVA measurement.
- The quotas are associated here only with the `ThrottlingException` responses. They are NOT claimed to
  explain the earlier `AccessDeniedException` in F-001; the two errors occurred in different time windows
  with different messages.
- NOT_ESTABLISHED: whether the 0 values are a consequence of the account being new, of the Free plan, or
  of something else. The support case asks AWS.

---

## F-003 -- Strands `BedrockModel` rejects `region_name` together with `boto_session`

| Field | Entry |
|---|---|
| Date (UTC) | 2026-09-30, 17:47:25Z |
| Task | Construct `BedrockModel` with a named-profile session (`boto3.Session(profile_name="eva-runtime", region_name="eu-north-1")`) and an explicit `region_name="eu-north-1"`, so that no default could apply |
| Expected | Both values given and consistent; construction succeeds |
| Actual | `ValueError: Cannot specify both region_name and boto_session.` (strands-agents 1.57.1, `strands/models/bedrock.py`, line 253). No Bedrock request was made. |
| Severity | Low -- fails fast before any network call; one wasted run |
| Workaround | Pass the region on the session only, then assert after construction that `model.client.meta.region_name == "eu-north-1"` and `model.config["model_id"] == "amazon.nova-lite-v1:0"`, and stop otherwise. Measured offline: the resolved client region is `eu-north-1`. |
| Suggestion | Accept both when they agree (raise only on a mismatch), or state the restriction in the `region_name` parameter documentation. Relatedly, when neither is given, `BedrockModel` silently falls back to `us-west-2` and a default model id; an opt-in "strict" mode that refuses defaults would help integrators that must pin model and region. |

Evidence (MEASURED):

```
evidence/i3b/RUNB_20260930T174725Z_proof.json   cc810312cad1fb24b6ce20664d16f8a56a411a9014ca396452057f1d9228264b  1215
```

Source read: strands-agents 1.57.1, `strands/models/bedrock.py` lines 253-257 (the check and the region
resolution order `region_name or session.region_name or AWS_REGION or us-west-2`).

---

## F-004 -- Root user and IAM user were easy to confuse in the console; access keys ended up on root

| Field | Entry |
|---|---|
| Date (UTC) | 2026-09-30, discovery phase (before 17:06Z) |
| Task | Create a least-privilege IAM user `eva-discovery` with an access key for read-only Bedrock discovery |
| Expected | An access key belonging to `user/eva-discovery` |
| Actual | At least three access keys in succession were created on the **root** user, each one discovered only when the caller-ARN check returned `...:root`. The console header showed "eva-discovery" -- which was the **account name**, not an IAM user -- while IAM showed Users = 0. The same name for the account and the intended IAM user made it look as if one were already acting as that user. |
| Severity | Medium -- a security risk (root access keys), not a functional block. Discovery ran once with root credentials before this was noticed; that run only read. |
| Workaround | Created the IAM users `eva-discovery` and `eva-runtime` from CloudShell with `aws iam create-user` / `put-user-policy` / `create-access-key`, so the key could not land on the wrong principal. Verified each identity by its caller ARN only (`sts get-caller-identity`), never by displaying the key. Earlier root access keys deactivated and deleted (the last one: see NOT_ESTABLISHED below); MFA assigned to root. |
| Suggestion | (1) When a user is about to create an access key on the root user, show an explicit interstitial ("You are creating a key for the ROOT user of this account"). (2) In the console header, label the account name as "Account:" distinct from the signed-in principal. |

Evidence (MEASURED):

```
D:\EVE11\tools\eva_aws_discovery\discovery_round1b.json
                                                4cfeff31608c3f1fcce29f9a5b7ee7c69dd8a27c2aa330a2228100bfed2f1a49  202159
  (identity: arn:aws:iam::633697460261:root -- the run made with a root key)
D:\EVE11\tools\eva_aws_discovery\discovery_round2b.json
                                                0cb730324785d54cf1fca7815a4c6fec3e212dfa5e425505c87174281495386d  76087
  (identity: arn:aws:iam::633697460261:user/eva-discovery -- after the correction)
```

OWNER_OBSERVED: IAM dashboard showing Users = 0 while the header read "eva-discovery"; root security
recommendations ("Deactivate or delete access keys for root user", "Add MFA for root user"); MFA
assigned to root (confirmation banner "MFA device assigned").

NOT_ESTABLISHED at the time of writing: that the last remaining root access key has been deleted (the
console last showed one root key with the Delete action open; deletion not yet confirmed).
