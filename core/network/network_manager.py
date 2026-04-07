# core/network/network.py
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from core.enums import Priority

class NetworkSnapshot:
    version: int = -1
    tab: dict[int, dict[str, any]]
    lvls: dict[Priority, list[int]]
    
class Network:
    snapshot: NetworkSnapshot = None
    pass

