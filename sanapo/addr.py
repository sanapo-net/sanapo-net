# sanapo/addr.py
from dataclasses import dataclass

@dataclass(frozen=True)
class Addr:
    unit: str
    system: str = "LOCAL"

    def is_local(self, current_sys: str) -> bool:
        """Quick check: is this unit in our process?"""
        return self.system == "LOCAL" or self.system == current_sys

    def to_net(self, current_sys: str) -> str:
        """For outgoing network frames: replaces LOCAL with real name."""
        s = current_sys if self.system == "LOCAL" else self.system
        return f"{s}:{self.unit}"

    def __str__(self):
        return f"{self.system}:{self.unit}"

    @classmethod
    def from_str(cls, addr_str: str) -> 'Addr':
        """Basic parser. Normalization happens in Broker.get_addr()."""
        if not addr_str: return None
        if ":" in addr_str:
            sys_part, unit_part = addr_str.split(":", 1)
            return cls(system=sys_part, unit=unit_part)
        return cls(system="LOCAL", unit=addr_str)
