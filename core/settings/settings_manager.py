# core/settings_manager.py

from core.enums import Addr
from core.settings.settings_icmp import SettingsICMP

class SettingsManager:
    def __init__(self, proxy_obj, sec_creator):
        self._icmp = SettingsICMP(proxy_obj) #, sec_creator(Addr.SETTINGS_ICMP))
        #self._icmp = SettingsPorts(proxy_obj, sec_creator(Addr.SETTINGS_PORTS))
        #self._icmp = SettingsSniffer(proxy_obj, sec_creator(Addr.SETTINGS_SNIFFER))
        #self._icmp = SettingsGate(proxy_obj, sec_creator(Addr.SETTINGS_GATE))
        #self._icmp = SettingsUI(proxy_obj, sec_creator(Addr.SETTINGS_UI))
        #self._icmp = SettingsDB(proxy_obj, sec_creator(Addr.SETTINGS_DB))

    @property
    def icmp(self) -> SettingsICMP: return self._icmp
