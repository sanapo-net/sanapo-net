# sanapo/manifest.py
from dataclasses import dataclass, field, asdict
from typing import Set, Dict, Any
from sanapo.enums import UnitRole
from sanapo.addr import Addr

@dataclass(frozen=True)
class Manifest:
    """Unit Passport. Defines identity, capabilities, and access levels."""
    uid: str                 # Unique instance ID (UUID)
    sid: str                 # System Name (from Config)
    addr: Addr               # Logic Address object
    version: str             # Logic/Module version
    
    # Capabilities
    tags: Set[str] = field(default_factory=set) 
    role: UnitRole = UnitRole.WORKER
    
    # Flags
    is_public: bool = False      # Share with other systems?
    is_autonomous: bool = False  # Passive/Slave mode?
    
    # Security
    auth_key: str = ""           # Future crypto signatures

    def to_dict(self) -> Dict[str, Any]:
        """Serializes manifest for network exchange."""
        data = asdict(self)
        data['addr'] = str(self.addr) # Addr object to "System:Unit" string
        data['role'] = self.role.value
        data['tags'] = list(self.tags) # set is not JSON serializable
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any], current_sys: str = None) -> 'Manifest':
        """Reconstructs manifest from dictionary with smart address normalization."""
        data['addr'] = Addr.from_str(data['addr'], current_sys)
        data['role'] = UnitRole(data.get('role', UnitRole.WORKER.value))
        data['tags'] = set(data.get('tags', []))
        return cls(**data)

