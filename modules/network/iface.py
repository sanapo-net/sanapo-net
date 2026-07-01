# modules/network/iface.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from common.enums import TickInterval, IfaceType, Priority
    from modules.network.device import Device
    from modules.network.link import Link


@dataclass
class Iface:
    uid: int
    type: IfaceType
    device: Device
    speed: int
    priority: Priority = Priority.LOW
    name: str = ""
    name_u: str = ""
    ip: str = ""
    mac: str = ""
    ip_is_dynamic: bool = False
    mac_is_dynamic: bool = False
    icmp_timeout: float = 0
    icmp_interval: TickInterval = None
    links: list[Link] = field(default_factory=list)
    opened_ports: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.icmp_interval is None:
            if "wifi" in self.type.value:
                self.icmp_interval = TickInterval.SEC_4
            else:
                self.icmp_interval = TickInterval.SEC_2