"""eve-mcp: a thin, deterministic MCP boundary over the EVE pre-action API.

Phase 1 scope: exactly one tool, `eve_pre_action`. No LLM, no consequential
action execution, no EVE-core modification. The EVE determination is passed
through verbatim; the adapter only adds transport, policy and adapter metadata.
"""
__all__ = ["core", "server"]
