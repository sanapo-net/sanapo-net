# core/buffer/buffer_manager.py
from typing import TYPE_CHECKING, Callable
if TYPE_CHECKING:
    from main import Tools
    from core.secretary import Secretary

from core.enums import Addr
from core.buffer.buffer_icmp import BufferICMP

class BufferManager:
    def __init__(self, tools: Tools, setup_module: Callable) -> None:
        self._tools: Tools = tools
        self._icmp = setup_module(Addr.BUFFER_ICMP, BufferICMP)

    @property
    def icmp(self) -> BufferICMP: return self._icmp
