from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sanapo.addr import Addr

@dataclass
class Manifest:
    """Unit Passport. Defines identity, capabilities, and access levels."""
    uid: str                 # Unique instance ID (UUID)
    sid: str                 # System Name (from Config)
    addr: Addr               # Logic Address object
    version: str             # Logic/Module version
    role: str                # Role in system (e.g., 'worker', 'gateway')
    
    # Capabilities (Set of skill tags)
    tags: set[str] = field(default_factory=set) 
    
    # Flags
    is_public: bool = False      # Share with other systems?
    is_autonomous: bool = False  # Passive/Slave mode?
    is_persistent: bool = True   # Save to dump for system consistency?
    
    # Security
    auth_key: str = ""           # Future crypto signatures

    def to_dict(self) -> dict[str, any]:
        """Serializes manifest to primitive types for network/disk exchange."""
        data = asdict(self)
        data['addr'] = str(self.addr)  # Convert Addr object to "System:Unit" string
        data['tags'] = list(self.tags) # Convert set to JSON-serializable list
        return data
