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
        """Attempts to read one Frame from the local queue."""
        try:
            frame = self.spec_addr.get_nowait()
            if frame:
                if isinstance(frame, Frame):
                    return {"frame": frame, "stat": TranspReadStat.OK, "raw": None}
                else:
                    return {"frame": None, "stat": TranspReadStat.CORRUPTED, "raw": frame}
            return {"frame": None, "stat": TranspReadStat.CORRUPTED, "raw": None}
        except Empty:
            return {"frame": None, "stat": TranspReadStat.EMPTY, "raw": None}
        except Exception as e:
            return {"frame": None, "stat": TranspReadStat.CORRUPTED, "raw": e}

    def is_empty(self) -> bool:
        return self.spec_addr.empty()
    
    def is_ready(self) -> bool:
        return True