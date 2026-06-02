# sanapo/addr.py
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class Addr:
    system: str
    unit: str

    def is_local(self, current_sys: str) -> bool:
        """Quick check: is this unit in our process?"""
        return self.system == current_sys

    def to_net(self, current_sys: str) -> str:
        """For outgoing network frames."""
        return f"{self.system}:{self.unit}"

    def __str__(self):
        return f"{self.system}:{self.unit}"
    
    def __repr__(self):
        return f"Addr({self.system}:{self.unit})"

    @classmethod
    def from_str(cls, addr_str: str) -> 'Addr' | None:
        """Basic parser."""
        if not addr_str or ":" not in addr_str: return None
        sys_part, unit_part = addr_str.split(":", 1)
        return cls(sys_part, unit_part)
