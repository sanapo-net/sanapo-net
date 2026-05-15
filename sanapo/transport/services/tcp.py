# transport/services/tcp.py
from __future__ import annotations
import socket
import threading
import struct
import json
from time import perf_counter
from typing import TYPE_CHECKING

from sanapo.protocol import Frame

if TYPE_CHECKING:
    from sanapo.config import Config
    from sanapo.logger import Logger
    from sanapo.message_broker import MessageBroker


class FrameStitcher:
    """Reconstructs Frames from a byte stream using a Magic Header (8b) and Length (4b)."""
    def __init__(self, config: Config):
        self._buffer = bytearray()
        self._magic: bytes = config.MAGIC_HEADER
        self._header_size = 12  # 8 (Magic) + 4 (Length)

    def put(self, data: bytes) -> list[bytes]:
        """Adds raw bytes to buffer and returns completed packets."""
        self._buffer.extend(data)
        packets = []
        
        while len(self._buffer) >= self._header_size:
            # Unpack: 8s (Magic string), I (Unsigned Int length).
            magic, length = struct.unpack('>8sI', self._buffer[:self._header_size])

            if magic != self._magic:
                # Security: invalid magic means we clear buffer and drop connection.
                self._buffer.clear()
                raise ValueError(f"Protocol Violation: Expected {self._magic}, got {magic}")
            
            if len(self._buffer) < self._header_size + length:
                break # Wait for the rest of the data

            packet = self._buffer[self._header_size : self._header_size + length]
            packets.append(packet)
            del self._buffer[:self._header_size + length]
            
        return packets


class TcpConnection(threading.Thread):
    """Individual thread for each socket to prevent blocking the main service."""
    def __init__(self, name: str, sock: socket.socket, addr: tuple, 
                 broker: MessageBroker, logger: Logger, config: Config):
        super().__init__(name=f"TCP-{name}", daemon=True)
        self.remote_system_name = name
        self.sock = sock
        self.addr = addr
        self._broker = broker
        self._log = logger
        self._cfg = config
        self.stitcher = FrameStitcher(config)
        self.last_rx = perf_counter()
        self.is_alive = True

    def run(self):
        """Continuous receiving loop with heartbeat check."""
        # Set a shorter timeout for recv to check idle time periodically
        self.sock.settimeout(5.0) 
        while self.is_alive:
            try:
                data = self.sock.recv(4096)
                if not data:
                    self.stop()
                    break
                
                self.last_rx = perf_counter()
                packets = self.stitcher.put(data)
                for raw_data in packets:
                    self._process_raw_frame(raw_data)

            except socket.timeout:
                if perf_counter() - self.last_rx > self._cfg.CONN_KEEP_ALIVE:
                    t = "TCP: Connection with {name} timed out."
                    self._log.wrn(t, name=self.remote_system_name)
                    self.stop()
                continue
            except ValueError as e:
                self._log.crt("TCP: Security violation from {addr}: {e}", addr=self.addr, e=e)
                self.stop()
            except Exception as e:
                if self.is_alive:
                    t = "TCP: Connection with {name} lost: {e}"
                    self._log.err(t, name=self.remote_system_name, e=e)
                self.stop()

    def _process_raw_frame(self, raw_data: bytes):
        """Converts raw bytes to dict and pushes to Broker bus for lazy reconstruction."""
        try:
            # Reconstruct is now moved to Secretary for performance
            data_dict = json.loads(raw_data.decode('utf-8'))
            self._broker.bus.put(data_dict)
        except Exception as e:
            t = "TCP: Failed to decode JSON from {name}: {e}"
            self._log.err(t, name=self.remote_system_name, e=e)

    def send_raw(self, data: bytes) -> bool:
        """Physical transmission over the wire."""
        try:
            self.sock.sendall(data)
            return True
        except Exception:
            return False

    def stop(self):
        """Graceful resource cleanup."""
        self.is_alive = False
        try:
            self.sock.close()
        except: 
            pass


class TcpService(threading.Thread):
    """Network Gateway. Manages listeners, handshakes, and federated routing."""
    def __init__(self, config: Config, broker: MessageBroker, logger: Logger):
        super().__init__(name="TcpService", daemon=True)
        self._cfg = config
        self._log = logger
        self._broker = broker
        
        self._is_running = False

        # Active connections registry.
        self._connections: dict[str, TcpConnection] = {}
        self._lock = threading.Lock()

    def run(self):
        """Main Listener Loop (Server Role)."""
        self._is_running = True
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind((self._cfg.HOST, self._cfg.TCP_PORT_DEFAULT))
                s.listen(5)
                address = f"{self._cfg.HOST}:{self._cfg.TCP_PORT_DEFAULT}"
                self._log.inf("TCP: Server listening on {address}", address=address)
                
                while self._is_running:
                    client_sock, addr = s.accept()
                    # Each handshake in a temporary thread to keep listener free.
                    threading.Thread(
                        target=self._inbound_handshake, 
                        args=(client_sock, addr), 
                        daemon=True
                    ).start()
        except Exception as e:
            self._log.crt("TCP: Listener crashed: {e}", e=e)

    def _inbound_handshake(self, sock: socket.socket, addr: tuple):
        """Initial contact protocol: verifies magic and system names."""
        try:
            sock.settimeout(self._cfg.HANDSHAKE_TIMEOUT)
            
            # 1. Receive Magic Header (8 bytes).
            guest_magic = sock.recv(8)
            if guest_magic != self._cfg.MAGIC_HEADER:
                self._log.wrn("TCP: Invalid magic from {addr}. Closing.", addr=addr)
                sock.close()
                return

            # 2. Receive System Name length and string.
            name_len_bytes = sock.recv(4)
            if not name_len_bytes: return
            name_len = struct.unpack('>I', name_len_bytes)[0]
            remote_name = sock.recv(name_len).decode('utf-8')

            # 3. Respond with local credentials.
            self._send_handshake_response(sock)

            # 4. Identity collision check.
            if self._cfg.SYSTEM_NAME == remote_name:
                self._log.err("TCP: System name collision: {name}", name=remote_name)
                sock.close()
                return

            self._register_connection(remote_name, sock, addr)
            
        except Exception as e:
            self._log.err("TCP: Handshake failed with {addr}: {e}", addr=addr, e=e)
            sock.close()

    def _send_handshake_response(self, sock: socket.socket):
        """Sends our magic and name back to the requester."""
        name_bytes = self._cfg.SYSTEM_NAME.encode('utf-8')
        # Response: MAGIC (8b) + NAME_LEN (4b) + NAME (string).
        header = self._cfg.MAGIC_HEADER + struct.pack('>I', len(name_bytes))
        sock.sendall(header + name_bytes)

    def _register_connection(self, name: str, sock: socket.socket, addr: tuple):
        """Registers the connection using the Alphabetical Tender logic."""
        with self._lock:
            if name in self._connections:
                # Tender: keep connection from system with 'higher' name.
                if self._cfg.SYSTEM_NAME > name:
                    t = "TCP: Higher rank system (us), keeping existing conn to {name}."
                    self._log.inf(t, name=name)
                    sock.close()
                    return
                else:
                    self._connections[name].stop()

            conn = TcpConnection(name, sock, addr, self._broker, self._log, self._cfg)
            self._connections[name] = conn
            conn.start()
            self._log.inf("TCP: Federation link with '{name}' established.", name=name)
            
            report = {
                "msg_type": "sys",
                "sub_type": "net_connected",
                "sender": "LOCAL:TCP_SERVICE",
                "recipient": "LOCAL:KERNEL",
                "payload": {"sys_name": name}
            }
            self._broker.bus.put(report)


    def send_to_system(self, system_name: str, payload: bytes) -> bool:
        """Sends to a named system (Federated routing)."""
        with self._lock:
            conn = self._connections.get(system_name)
        if conn and conn.is_alive:
            return self._send_with_header(conn, payload)
        return False

    def send_to_addr(self, addr: tuple, payload: bytes) -> bool:
        """Sends to a specific physical address (Slave/Local units)."""
        with self._lock:
            for conn in self._connections.values():
                if conn.addr == addr and conn.is_alive:
                    return self._send_with_header(conn, payload)
        return False

    def _send_with_header(self, conn: TcpConnection, payload: bytes) -> bool:
        """Internal helper to add protocol framing before sending."""
        try:
            # Package: [MAGIC (8b)] + [LENGTH (4b)] + [DATA].
            header = struct.pack('>8sI', self._cfg.MAGIC_HEADER, len(payload))
            return conn.send_raw(header + payload)
        except Exception as e:
            self._log.err("TCP: Framing error for {name}: {e}", e=e, name=conn.remote_system_name)
            return False
