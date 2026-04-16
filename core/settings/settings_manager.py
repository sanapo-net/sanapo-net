# core/settings_manager.py
from typing import TYPE_CHECKING, Callable
if TYPE_CHECKING:
    from main import Tools
    from core.secretary import Secretary
    from core.enums import Addr

from core.enums import Addr
from core.settings.settings_icmp import SettingsICMP

# TODO Check and resolve the issue of deleting core/settings/settings_icmp.py
class ScanSettings():
    from core.enums import TickInterval
    timeouts = {
        TickInterval.SEC_05: 0.4,
        TickInterval.SEC_1: 0.9,
        TickInterval.SEC_2: 0.9,
        TickInterval.SEC_4: 0.9,
        TickInterval.SEC_8: 0.9
    }

class SettingsManager:
    def __init__(self, tools:Tools, setup_module: Callable) -> None:
        self._tools: Tools = tools
        self._icmp = SettingsICMP(tools)
        self._scan = ScanSettings()

    @property
    def icmp(self) -> SettingsICMP: return self._icmp

    @property
    def scan(self) -> ScanSettings: return self._scan
