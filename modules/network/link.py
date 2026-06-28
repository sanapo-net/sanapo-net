# modules/network/link.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from common.enums import IfaceType, Priority
from common.exceptions import IncompatibleInterfacesError

if TYPE_CHECKING:
    from modules.network.iface import Iface

@dataclass(frozen=True)
class Link:
    """Represents a physical or wireless network connection between two interfaces."""
    uid: int
    ifaces: list[Iface]
    type: IfaceType = IfaceType.UNKNOWN
    speed: int = 0
    
    # Metadata fields: Excluded from hash and compare to allow safe external editing
    priority: Priority = field(default=Priority.LOW, compare=False, hash=False)
    name: str = field(default="", compare=False, hash=False)

    def __post_init__(self):
        """Validates connection compatibility and builds network topology graph links."""
        # Validation
        if len(self.ifaces) != 2:
            raise ValueError("Link must have exactly two interfaces")
            
        iface1, iface2 = self.ifaces[0], self.ifaces[1]
        p1, p2 = iface1.type, iface2.type
        
        is_valid = False
        if ("wifi" in p1.value and "wifi" in p2.value) or p1 == p2:
            is_valid = True
            
        if not is_valid:
            raise IncompatibleInterfacesError(f"Cannot connect {p1.value} to {p2.value}.")
        
        # Get type
        if "wifi" in p1.value:
            object.__setattr__(self, 'type', p1 if p1.generation < p2.generation else p2)
        else:
            object.__setattr__(self, 'type', p1)

        # Get speed
        object.__setattr__(self, 'speed', min(iface1.speed, iface2.speed))

        # Make hookup
        iface1.links.append(self)
        iface2.links.append(self) # Non-atomic operation (thread attention)
