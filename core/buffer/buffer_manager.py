# core/buffer/buffer_manager.py

from core.enums import Addr
from core.buffer.buffer_icmp import BufferICMP

class BufferManager:
    def __init__(self, proxy_obj, sec_creator):
        self._icmp = BufferICMP(proxy_obj, sec_creator(Addr.BUFFER_ICMP))
        #self._tcp = BufferTCP(proxy_obj, sec_creator(Addr.BUFFER_TCP)) # in future
        #self._snf = BufferDiscovery(proxy_obj, sec_creator(Addr.BUFFER_DISCOVERY)) # in future

    @property
    def icmp(self) -> BufferICMP: return self._icmp
