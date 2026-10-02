# Correction notice -- INVENTORY_HANDOFF_CHAIN_OFFLINE_2026-10-01.md (2026-10-02)

The corrected document is left unchanged:
docs/INVENTORY_HANDOFF_CHAIN_OFFLINE_2026-10-01.md, sha256
2dad0614b225dfd9865450ff04d58bccbeee7bcf771c3cd5590a702ff59db16f, git blob
fefa37d4ddbdb4ac31ddc4a0e1a3b22f8df5d34a, committed in c714e22322fa5478004a486963b73114f03b4de4.

## What was wrong

The inventory used D:\EVE11\staging\core_freeze_candidate as "the isolated copy of the eve-core-v1
candidate tree" and marked its tree identity FROM_MEMORY_NOT_REMEASURED (a698922c...). Measured on
2026-10-02, that is not the case:

| Checkout | HEAD^{tree} |
|---|---|
| D:\EVE11\staging\core_freeze_candidate | 937f4f7311c2c2fcf119342d4e9b24998641ddf2 |
| D:\EVE_DEMO\eve-core-v1 (eve-core-v1) | a698922c9fd740c4b114e572a626380abf1590a4 |

## Direct measurements in eve-core-v1

Source: git ls-tree HEAD core/eve_chain/ in D:\EVE_DEMO\eve-core-v1 (tree
a698922c9fd740c4b114e572a626380abf1590a4), 25 entries.

| Item | Measured in eve-core-v1 |
|---|---|
| Verified Handoff (verified_handoff*.py) | absent -- NOT_IN_EVE_CORE_V1, now measured directly |
| H7 core/eve_chain/h7_context_binding.py | present, git blob 304c1cc30487f5f6b08079626d6a50b7e53fea30 |
| G3 core/eve_chain/handling_evidence.py | present, git blob e8358a1204ff9bdbd2dcc7d747f6159cc71d84c7 |

The two files hashed for the inventory (sha256 5eefcc48d56020153c6cdf57a739233abcf4bbf25220e30d939072ee8885a2f6
and 29219d7538f3697eedaf14201c4ec578da901dc1281816282533d315534fedce) have exactly these git blob ids, so
the identities given in the inventory are the eve-core-v1 contents.

## Effect

The conclusions of the inventory are unchanged. Only its reference point is corrected: statements
about "the frozen core copy" are now established against eve-core-v1 itself (tree a698922c...), not
against D:\EVE11\staging\core_freeze_candidate.
