# common/enums.py
from enum import Enum


class Priority(str, Enum):
    HIGH  = "high"
    MEDIUM  = "medium"
    LOW = "low"


class DeviceType(str, Enum):
    UNKNOWN = "unknown"
    PC = "pc"
    LAPTOP = "LAPTOP"


class IfaceType(Enum):
    UNKNOWN = "unknown"
    # WiFi family
    WIFI_SOME = "wifi_some"
    WIFI_4 = "wifi_4"
    WIFI_5 = "wifi_5"
    WIFI_6 = "wifi_6"
    WIFI_6E = "wifi_6e"
    WIFI_7 = "wifi_7"
    # Copper family
    COPPER = "copper"
    # Fiber family
    FIBER_SINGLE = "fiber_single"
    FIBER_MULTI = "fiber_multi"
    
    @property
    def generation(self) -> int:
        """Returns the chronological weight of the standard for comparison."""
        weights = {
            IfaceType.WIFI_SOME: 0,
            IfaceType.WIFI_4: 4,
            IfaceType.WIFI_5: 5,
            IfaceType.WIFI_6: 6,
            IfaceType.WIFI_6E: 7,
            IfaceType.WIFI_7: 8
        }
        return weights.get(self, 0)


class TickInterval(float, Enum):
    """Physical time constants in seconds."""
    OFF      = -100.0
    DEFAULT  = -1.0
    SEC_05   = 0.5
    SEC_1    = 1.0
    SEC_2    = 2.0
    SEC_4    = 4.0
    SEC_8    = 8.0
    SEC_24   = 24.0
    SEC_120  = 120.0