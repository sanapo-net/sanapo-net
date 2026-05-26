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
    def __init__(self, sanapo_addr: Addr, sys_name: str, host: str | None, port: int | None, service: TcpService):
        # Explicit and strict check for the presence of a device's physical host
        spec = (host, port) if (host is not None and port is not None) else sys_name
        super().__init__(sanapo_addr=sanapo_addr, spec_addr=spec)
        self._service: TcpService = service
        self._sys_name: str = sys_name
        
        # Buffer for raw dicts from the network.
        self._inbox: queue.Queue[dict] = queue.Queue()

    def send(self, payload: Frame | dict) -> bool:
        """
        Smart forwarding for both Federation links and dedicated raw TCP units.
        Accepts both Frame and raw dict payloads.
        """
        if not self.is_ready():
            return False
        try:
            # Packed byte JSON is always sent to the network
            raw_dict = payload.to_dict() if isinstance(payload, Frame) else payload
            raw_data = json.dumps(raw_dict).encode('utf-8')

            # Если в spec_addr лежит строка (имя внешней системы федерации)
            if isinstance(self.spec_addr, str):
                return self._service.send_to_system(self.spec_addr, raw_data)
            
            # Если в spec_addr лежит кортеж (host, port) — это наш "откомандированный" юнит
            return self._service.send_to_addr(self.spec_addr, raw_data)
            
        except Exception:
            return False

    def inject_received(self, data: dict) -> None:
        """Inbound gate for TcpService to push data into this transport buffer."""
        self._inbox.put(data)

    def read(self) -> dict[str, any]:
        """Reads one raw dictionary from the internal buffer."""
        try:
            raw_data = self._inbox.get_nowait()
            return {"frame": None, "stat": TranspReadStat.OK, "raw": raw_data}
        except queue.Empty:
            return {"frame": None, "stat": TranspReadStat.EMPTY, "raw": None}

    def is_empty(self) -> bool:
        """Checks if there are buffered frames to read."""
        return self._inbox.empty()

    def is_ready(self) -> bool:
        """Checks if the network service and target are available."""
        if isinstance(self.spec_addr, str):
            return self._service.is_conn_alive(self.spec_addr)
        return self._service.is_conn_alive_addr(self.spec_addr)

