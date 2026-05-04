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
        
        # Buffer for reconstructed frames from the network.
        self._inbox: queue.Queue[Frame] = queue.Queue()

    def send(self, frame: Frame) -> bool:
        """
        Smart forwarding: if the address is external, it sends by system name;
        if it's local on TCP, it sends by physical address.
        """
        try:
            payload = self._frame_to_spec(frame)
            
            # If the address indicates a different system (Federation).
            if frame.recipient.system != "LOCAL" and frame.recipient.system != self._sys_name:
                return self._service.send_to_system(frame.recipient.system, payload)
            
            # For local TCP-Unit.
            return self._service.send_to_addr(self.spec_addr, payload)
            
        except Exception:
            return False

    def read(self) -> dict[str, any]:
        """Reads one reconstructed frame from the internal buffer."""
        try:
            frame = self._inbox.get_nowait()
            return {"frame": frame, "stat": TranspReadStat.OK, "raw": None}
        except queue.Empty:
            return {"frame": None, "stat": TranspReadStat.EMPTY, "raw": None}

    def is_empty(self) -> bool:
        """Checks if there are buffered frames to read."""
        return self._inbox.empty()

    def is_ready(self) -> bool:
        """Checks if the network service and target are available."""
        return self._service.is_alive(self.spec_addr)
    
    def _frame_to_spec(self, frame: Frame) -> bytes:
        """Serializes Frame to bytes: [SanaPo10 (8b)] + [Length (4b)] + [Data]."""
        raw_data = frame.to_dict()
        return json.dumps(raw_data).encode('utf-8')

    def _spec_to_frame(self, raw_bytes: bytes) -> Frame:
        """Deserializes raw bytes back into a Frame object."""
        data_dict = json.loads(raw_bytes.decode('utf-8'))
        return Frame.from_dict(data_dict)