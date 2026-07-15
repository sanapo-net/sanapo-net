# common/config.py
from __future__ import annotations
from common.enums import TickInterval

class Config:
    """For parameters that can be changed during program debugging"""

    # Allowed ICMP timeouts (ms)
    ICMP_TIMEOUTS = [0.2, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 5.0, 7.0]
