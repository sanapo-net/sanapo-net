# core/buffer/buffer_manager.py
from __future__ import annotations
from typing import TYPE_CHECKING, Callable

from core.enums import Addr
from core.buffer.buffer_icmp import BufferICMP

if TYPE_CHECKING:
    from main import Tools
    from core.secretary import Secretary

class BufferManager:
    def __init__(self, tools: Tools, setup_module: Callable) -> None:
        self._tools: Tools = tools
        self._icmp = setup_module(Addr.BUFFER_ICMP, BufferICMP)

    @property
    def icmp(self) -> BufferICMP: return self._icmp
