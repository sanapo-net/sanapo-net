# transport/adapters/tcp.py
from __future__ import annotations
import json
import queue
from typing import TYPE_CHECKING

from sanapo.transport.adapters import BaseAdapterTransport
from sanapo.enums import TranspReadStat
from sanapo.protocol import Frame

if TYPE_CHECKING:
    from sanapo.transport.services.tcp import TcpService
    from sanapo.addr import Addr

class TcpAdapterTransport(BaseAdapterTransport):
    """TCP Transport Adapter. Handles network delivery and frame reconstruction."""
    def __init__(self, sanapo_addr: Addr, sys_name: str, host: str, port: int, service: TcpService):
        # spec_addr for TCP is a (host, port) tuple.
        super().__init__(sanapo_addr=sanapo_addr, spec_addr=(host, port))
        self._service = service
        self._sys_name = sys_name
        
        # Buffer for raw dicts from the network.
        self._inbox: queue.Queue[dict] = queue.Queue()

    def send(self, frame: Frame) -> bool:
        """
        Smart forwarding: if the address is external, it sends by system name;
        if it's local on TCP, it sends by physical address.
        """
        try:
            payload = self._frame_to_spec(frame)
            
            # Use Addr object's own logic to check locality.
            if not frame.recipient.is_local(self._sys_name):
                return self._service.send_to_system(frame.recipient.system, payload)
            
            # For local TCP-Unit.
            return self._service.send_to_addr(self.spec_addr, payload)
            
        except Exception:
            return False


    def read(self) -> dict[str, any]:
        """Reads one raw dictionary from the internal buffer."""
        try:
            raw_data = self._inbox.get_nowait()
            return {"frame": raw_data, "stat": TranspReadStat.OK, "raw": raw_data}
        except queue.Empty:
            return {"frame": None, "stat": TranspReadStat.EMPTY, "raw": None}

    def is_empty(self) -> bool:
        """Checks if there are buffered frames to read."""
        return self._inbox.empty()

    def is_ready(self) -> bool:
        """Checks if the network service and target are available."""
        return self._service.is_alive(self.spec_addr)
    
    def _frame_to_spec(self, frame: Frame) -> bytes:
        """Serializes Frame to bytes"""
        raw_data = frame.to_dict()
        return json.dumps(raw_data).encode('utf-8')
