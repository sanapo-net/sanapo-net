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
