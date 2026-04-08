# core/settings_manager.py
from typing import TYPE_CHECKING, Callable
if TYPE_CHECKING:
    from main import Tools
    from core.secretary import Secretary
    from core.enums import Addr

from core.enums import Addr
from core.settings.settings_icmp import SettingsICMP

class SettingsManager:
    def __init__(self, tools:Tools, registration: Callable) -> None:
        self._icmp = SettingsICMP(tools)

    @property
    def icmp(self) -> SettingsICMP: return self._icmp
