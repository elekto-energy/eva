"""EVA chain intake (product core, step 1).

Customer- or operator-declared evidence -> strict validation -> a new, immutable, content-addressed
EVE chain composed by EVE's own engine (via the vendored EVE MCP v1 scenario builder, unchanged) ->
equivalence gate against resolve() -> available to the existing EVA/EVE boundary.

It never overwrites a chain, never fills in a missing field, never judges whether declared evidence is
true, and never changes EVE core, EVE MCP v1 or the frozen I3A boundary.
"""
