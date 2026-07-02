# modules/network/device.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from common.enums import DeviceType, Priority
    from modules.network.iface import Iface


@dataclass
class Device:
    uid: int
    type: DeviceType = DeviceType.UNKNOWN
    priority: Priority = Priority.LOW
    ifaces: list[Iface] = field(default_factory=list)  
    name: str = ""         # str(31)
    name_u: str = ""       # str(31)
    tags: str = ""         # str(255)
    os: str = "UNKNOWN"    # str(31)
    brand: str = "UNKNOWN" # str(31)
    dnsname: str = "UNKNOWN" # str(255)