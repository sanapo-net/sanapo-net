# sanapo/addr.py
from dataclasses import dataclass

@dataclass(frozen=True)
class Addr:
    """Unified address object for local and federated routing."""
    unit: str                # Unit logic name (e.g. 'SCANNER')
    system: str = "LOCAL"    # System name for federation (default: LOCAL)

    def __str__(self):
        return f"{self.system}:{self.unit}"

    def is_local(self, current_system_name: str) -> bool:
        return self.system == "LOCAL" or self.system == current_system_name

    @classmethod
    def from_str(cls, addr_str: str) -> 'Addr':
        """Parses string "SYSTEM:UNIT" or "UNIT" into Addr object."""
        if not addr_str:
            return None
        
        if ":" in addr_str:
            sys_part, unit_part = addr_str.split(":", 1)
            return cls(system=sys_part, unit=unit_part)
        
        return cls(system="LOCAL", unit=addr_str)