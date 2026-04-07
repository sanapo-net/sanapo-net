# core/buffer/buffer_manager.py
from typing import TYPE_CHECKING, Callable
if TYPE_CHECKING:
    from main import Tools
    from core.secretary import Secretary

from core.enums import Addr
from core.buffer.buffer_icmp import BufferICMP

class BufferManager:
    def __init__(self, tools: Tools, get_secr: Callable[[str], Secretary]) -> None:
        self._icmp = BufferICMP(tools, get_secr(Addr.BUFFER_ICMP))
        #self._tcp = BufferTCP(proxy_obj, sec_creator(Addr.BUFFER_TCP)) # in future
        #self._snf = BufferDiscovery(proxy_obj, sec_creator(Addr.BUFFER_DISCOVERY)) # in future

    @property
    def icmp(self) -> BufferICMP: return self._icmp
