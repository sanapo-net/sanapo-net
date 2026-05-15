# sanapo/transport/services/udp.py
import socket
import threading
import struct
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sanapo.config import Config
    from sanapo.logger import Logger
    from sanapo.transport.services.tcp import TcpService

class UdpBeacon(threading.Thread):
    """UDP Beacon for automatic service discovery in LAN."""
    def __init__(self, config: Config, logger: Logger):
        super().__init__(name="UdpBeacon", daemon=True)
        self._cfg: Config = config
        self._log: Logger = logger
        self._is_running = False
        
        # Binary signal: [Magic (8b)] + [TCP_Port (4b)] + [SystemName_Len (4b)] + [SystemName]
        self._name_bytes = self._cfg.SYSTEM_NAME.encode('utf-8')
        self._packet = struct.pack(
            f'>8sII{len(self._name_bytes)}s',
            self._cfg.MAGIC_HEADER,
            self._cfg.TCP_PORT_DEFAULT,
            len(self._name_bytes),
            self._name_bytes
        )

    def run(self):
        """Broadcasts the system identity at regular intervals."""
        self._is_running = True
        # AF_INET = IPv4, SOCK_DGRAM = UDP
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            # Enable broadcasting
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            
            self._log.inf("UDP: Beacon started for '{name}'", name=self._cfg.SYSTEM_NAME)
            
            while self._is_running:
                try:
                    # Send to the whole local network
                    s.sendto(self._packet, ('<broadcast>', self._cfg.UDP_PORT_DEFAULT))
                except Exception as e:
                    self._log.err("UDP: Beacon send error: {e}", e=e)
                
                time.sleep(self._cfg.UDP_BEACON_INTERVAL)

    def stop(self):
        self._is_running = False

class UdpListener(threading.Thread):
    """Listens for beacons from other sanapo systems."""
    def __init__(self, config: Config, logger: Logger, tcp_service: TcpService):
        super().__init__(name="UdpListener", daemon=True)
        self._cfg: Config = config
        self._log: Logger = logger
        self._tcp_service: TcpService = tcp_service
        self._is_running = False

    def run(self):
        self._is_running = True
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            # Bind to all interfaces to catch broadcasts
            s.bind(('', self._cfg.UDP_PORT_DEFAULT))
            
            self._log.inf("UDP: Listener active, waiting for neighbors...")
            
            while self._is_running:
                try:
                    data, addr = s.recvfrom(1024)
                    self._process_beacon(data, addr)
                except Exception as e:
                    self._log.err("UDP: Listener error: {e}", e=e)

    def _process_beacon(self, data: bytes, addr: tuple):
        """Parses incoming beacon and initiates TCP connection if new."""
        try:
            # First check if it's even worth unpacking (header size)
            if len(data) < 16: return
            
            # Unpack magic first
            magic = struct.unpack('>8s', data[:8])[0]
            if magic != self._cfg.MAGIC_HEADER: return

            # Unpack the rest
            _, port, name_len = struct.unpack('>8sII', data[:16])
            remote_name = data[16:16+name_len].decode('utf-8')

            # Don't connect to ourselves
            if remote_name == self._cfg.SYSTEM_NAME: return

            # If it's a new system - tell TCP Service to go visit it!
            self._tcp_service.connect_to(addr[0], port)
            
        except Exception:
            pass # Ignore malformed beacons
