# sanapo/manifest.py
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sanapo.addr import Addr

@dataclass
class Manifest:
    addr: Addr               # Logical address (e.g., NODE_A:worker_1)
    version: str             # Module logic version
    role: str                # System role (e.g., 'worker', 'gateway')
    tags: set[str] = field(default_factory=set) # set of tags/skills
    
    # Local control flags inside the Kernel
    is_public: bool = False      # Expose this unit to the public network?
    is_persistent: bool = True   # Save to a local json dump?

    def to_dict(self) -> dict[str, any]:
        data = asdict(self)
        data['addr'] = str(self.addr)
        data['tags'] = list(self.tags)
        return data
