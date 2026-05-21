# transport/adapters/queue.py
from __future__ import annotations
from queue import Queue, Full, Empty
from typing import TYPE_CHECKING

from sanapo.transport.adapters import BaseAdapterTransport
from sanapo.enums import TranspReadStat

if TYPE_CHECKING:
    from sanapo.protocol import Frame
    from sanapo.addr import Addr

class QueueAdapterTransport(BaseAdapterTransport):
    """Ultra-fast in-process transport using Python Queues."""
    def __init__(self, sanapo_addr: Addr, inbox: Queue):
        super().__init__(sanapo_addr=sanapo_addr, spec_addr=inbox)

    def send(self, frame: Frame) -> bool:
        try:
            self.spec_addr.put(frame, block=False)
            return True
        except Full:
            return False
    
    def read(self) -> dict[str, any]:
        """Reads a frame or raw dict from the queue safely."""
        try:
            data = self.spec_addr.get_nowait()
            if data is None:
                return {"frame": None, "stat": TranspReadStat.CORRUPTED, "raw": None}
                
            if isinstance(data, Frame):
                return {"frame": data, "stat": TranspReadStat.OK, "raw": None}
            
            if isinstance(data, dict):
                return {"frame": None, "stat": TranspReadStat.OK, "raw": data}
                
            return {"frame": None, "stat": TranspReadStat.CORRUPTED, "raw": data}
            
        except Empty:
            return {"frame": None, "stat": TranspReadStat.EMPTY, "raw": None}
        except Exception as e:
            return {"frame": None, "stat": TranspReadStat.CORRUPTED, "raw": e}

    def is_empty(self) -> bool:
        return self.spec_addr.empty()

    def is_ready(self) -> bool:
        return True
