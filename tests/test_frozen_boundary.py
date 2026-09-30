"""I3 Del B guard: the five I3A boundary files must be byte-identical to the accepted I3A state."""
from eva.frozen import FROZEN_I3A_BOUNDARY, verify_frozen_boundary


def test_i3a_boundary_is_byte_frozen():
    assert set(FROZEN_I3A_BOUNDARY) == {"eva/gate.py", "eva/authorization.py", "eva/tools.py",
                                        "eva/data/chain_map.json", "eva/eve_client.py"}
    assert verify_frozen_boundary() == FROZEN_I3A_BOUNDARY
