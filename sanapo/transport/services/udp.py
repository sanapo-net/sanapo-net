# sanapo/transport/services/udp.py
from __future__ import annotations
import socket
import threading
import struct
import json
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
        # Start time for interval switching
        self._start_time: float = 0.0

    def run(self):
        """Broadcasts the system identity at variable intervals."""
        self._is_running = True
        self._start_time = time.perf_counter()

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self._log.inf("UDP: Beacon started as '{name}'", name=self._cfg.SYSTEM_NAME)

            while self._is_running:
                if self._cfg.NET_BEACON:
                    self._send_beacon(sock)

                # Interval selection
                elapsed = time.perf_counter() - self._start_time
                if elapsed < self._cfg.BEACON_SHORT_DURATION:
                    interval = self._cfg.BEACON_SHORT_INTERVAL
                else:
                    interval = self._cfg.BEACON_LONG_INTERVAL
                time.sleep(interval)

    def _send_beacon(self, sock: socket.socket) -> None:
        """Sends beacon as type 14 packet."""
        payload = {
            "port": self._cfg.TCP_PORT_DEFAULT,
            "system_name": self._cfg.SYSTEM_NAME
        }
        data = json.dumps(payload).encode('utf-8')

        header = (
            self._cfg.MAGIC_HEADER
            + self._cfg.NET_PROJECT_TOKEN
            + struct.pack(">B", 14)          # TYPE = 14
            + struct.pack(">I", len(data))
        )
        packet = header + data
        try:
            sock.sendto(packet, ('<broadcast>', self._cfg.UDP_PORT_DEFAULT))
        except Exception as e:
            self._log.err("UDP: Beacon send error: {e}", e=e)

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
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(('', self._cfg.UDP_PORT_DEFAULT))
            sock.settimeout(0.2)
            self._flush_buffer(sock)
            self._log.inf("UDP: Listener active")

            while self._is_running:
                try:
                    data, addr = sock.recvfrom(1024)
                    self._process_beacon(data, addr)
                except socket.timeout:
                    continue
                except Exception as e:
                    self._log.err("UDP: Listener error: {e}", e=e)

    def _flush_buffer(self, sock: socket.socket):
        """Discard all pending datagrams currently sitting in the OS socket buffer."""
        old_timeout = sock.gettimeout()
        try:
            sock.setblocking(False)
            while True:
                sock.recvfrom(65535)
        except BlockingIOError:
            pass
        finally:
            sock.settimeout(old_timeout)

    def _process_beacon(self, data: bytes, addr: tuple):
        """Parses incoming beacon (type 14) and initiates TCP connection if new."""
        if not self._cfg.NET_AUTO_CONNECT_BY_BEACON:
            return
        try:
            if len(data) < 19: # Minimum header length
                return

            magic = data[0:8]
            token = data[8:14]
            if magic != self._cfg.MAGIC_HEADER:
                return

            # Token check with NET_PROJECT_MONO
            if self._cfg.NET_PROJECT_MONO and token != self._cfg.NET_PROJECT_TOKEN:
                return

            (msg_type,) = struct.unpack(">B", data[14:15])
            (length,) = struct.unpack(">I", data[15:19])

            if msg_type != 14: # Only beacon expected
                return

            if len(data) < 19 + length:
                return

            payload_bytes = data[19:19+length]
            payload = json.loads(payload_bytes.decode('utf-8'))
            remote_name = payload.get("system_name")
            port = payload.get("port")

            if not remote_name or not port:
                return

            if remote_name == self._cfg.SYSTEM_NAME: # Ignore self
                return
            if self._tcp_service.is_conn_alive(remote_name):
                return

            # Replace local IP with loopback
            target_ip = addr[0]
            my_local_ip = socket.gethostbyname(socket.gethostname())
            if (target_ip == my_local_ip or
                target_ip == "0.0.0.0" or
                target_ip.startswith("127.") or
                target_ip == "::1"):
                target_ip = "127.0.0.1"

            self._tcp_service.connect_to(target_ip, port)

        except Exception as e:
            self._log.err("UDP: process beacon problems: {e}", e=e)