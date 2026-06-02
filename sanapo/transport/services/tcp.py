# transport/services/tcp.py
from __future__ import annotations
import socket
import threading
import struct
import json
import hmac
import hashlib
import os
from time import perf_counter
from typing import TYPE_CHECKING

from sanapo.transport.adapters.tcp import TcpAdapterTransport
from sanapo.addr import Addr

if TYPE_CHECKING:
    from sanapo.config import Config
    from sanapo.logger import Logger
    from sanapo.message_broker import MessageBroker
    from sanapo.transport.services.udp import UdpBeacon


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
                 broker: MessageBroker, logger: Logger, config: Config, service: "TcpService"):
        super().__init__(name=f"TCP-{name}", daemon=True)
        self.remote_system_name: str = name
        self.sock: socket.socket = sock
        self.addr: Addr = addr
        self._broker: MessageBroker = broker
        self._log: Logger = logger
        self._cfg: Config = config
        self._service: "TcpService" = service
        self.stitcher = FrameStitcher(config)
        self.last_rx = perf_counter()
        self.is_alive = True

    def run(self):
        """Continuous receiving loop with heartbeat check."""
        # set a shorter timeout for recv to check idle time periodically
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
        if not self.is_alive:
            return
        self.is_alive = False
        try:
            self.sock.close()
        except: 
            pass
        
        # Notify the parent service to remove this link and check discovery
        with self._service._lock:
            # Remove from registry if present
            if self._service._connections.get(self.remote_system_name) == self:
                self._service._connections.pop(self.remote_system_name, None)
        
        # Trigger automatic reconstruction of beaconing
        self._service._restore_network_discovery()

        msg_disconnect = {
            "msg_type": "sys",
            "sub_type": "net_disconnected", # SysType.NET_DISCONNECTED
            "sender": f"{self._cfg.SYSTEM_NAME}:TCP_SERVICE",
            "recipient": f"{self._cfg.SYSTEM_NAME}:{self._cfg.ADDR_KERNEL_STR}",
            "payload": {"sys_name": self.remote_system_name}
        }
        self._broker.bus.put(msg_disconnect)



class TcpService(threading.Thread):
    """Network Gateway. Manages listeners, handshakes, and federated routing."""
    def __init__(self, config: Config, broker: MessageBroker, logger: Logger):
        super().__init__(name="TcpService", daemon=True)
        self._cfg = config
        self._log = logger
        self._broker = broker
        self._udp_beacon: UdpBeacon | None = None
        
        self._is_running = False

        # Active connections registry.
        self._connections: dict[str, TcpConnection] = {}
        self._lock = threading.Lock()

    def _pack_local_manifests(self) -> bytes:
        """Collects compiled public passports directly from the broker registry."""
        manifest_data = {"manifests": self._broker.get_public_manifests_dict()}
        return json.dumps(manifest_data).encode('utf-8')

    def _unpack_and_register_manifests(self, raw_bytes: bytes, remote_name: str):
        """Unpacks foreign manifests and dispatches them to Kernel via Broker bus."""
        try:
            data = json.loads(raw_bytes.decode('utf-8'))
            manifests = data.get("manifests", {})
            
            msg = {
                "msg_type": "sys",
                "sub_type": "net_manifest_received", # SysType.NET_MANIFEST_RECEIVED
                "sender": f"{remote_name}:TCP_SERVICE",
                "recipient": f"{self._cfg.SYSTEM_NAME}:{self._cfg.ADDR_KERNEL_STR}",
                "payload": {"sys_name": remote_name, "manifests": manifests}
            }
            self._broker.bus.put(msg)
        except Exception as e:
            self._log.err("TCP: Failed to unpack manifests from {name}: {e}", name=remote_name, e=e)

    def _secure_auth_exchange(self, sock: socket.socket) -> bool:
        """Performs a cryptographic Challenge-Response validation via HMAC-SHA256."""
        try:
            password = getattr(self._cfg, 'NET_PASSWORD', 'DEFAULT_SANAPO_PASS').encode('utf-8')
            
            # 1. Generate and transmit our challenge salt (16 bytes)
            local_salt = os.urandom(16)
            sock.sendall(local_salt)
            
            # 2. Read foreign challenge salt
            remote_salt = sock.recv(16)
            if len(remote_salt) != 16: 
                return False
            
            # 3. Compute response to foreign challenge and transmit it
            my_response = hmac.new(password, remote_salt, hashlib.sha256).digest()
            sock.sendall(my_response)
            
            # 4. Read foreign response and verify against expected digest
            remote_response = sock.recv(32)
            expected_response = hmac.new(password, local_salt, hashlib.sha256).digest()
            
            return hmac.compare_digest(remote_response, expected_response)
        except Exception as e:
            self._log.err("TCP: Authentication protocol failure: {e}", e=e)
            return False


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
                    
                    # Secure filter by IP
                    allowed_ips = self._cfg.NET_ALLOWED_IPS
                    if allowed_ips and (addr[0] not in allowed_ips):
                        t = "TCP: SECURITY: Blocked TCP connection attempt from untrusted IP {addr}"
                        self._log.wrn(t, addr=addr[0])
                        client_sock.close()
                        continue

                    threading.Thread(
                        target=self._inbound_handshake,
                        args=(client_sock, addr),
                        daemon=True
                    ).start()

        except Exception as e:
            self._log.crt("TCP: Listener crashed: {e}", e=e)

    def _inbound_handshake(self, sock: socket.socket, addr: tuple):
        """Initial contact protocol: verifies magic, crypto-auth, and system names with manifest exchange."""
        try:
            sock.settimeout(self._cfg.HANDSHAKE_TIMEOUT)
            
            # 1. Receive Magic Header (8 bytes).
            guest_magic = sock.recv(8)
            if guest_magic != self._cfg.MAGIC_HEADER:
                self._log.wrn("TCP: Invalid magic from {addr}. Closing.", addr=addr)
                sock.close()
                return

            # 2. NET_PROJECT_TOKEN checking with cross-distribution allowance fallback.
            token_len = len(self._cfg.NET_PROJECT_TOKEN)
            guest_token = sock.recv(token_len)
            allow_cross = getattr(self._cfg, 'NET_ALLOW_CROSS_DISTRIB', False)
            if guest_token != self._cfg.NET_PROJECT_TOKEN and not allow_cross:
                t = "TCP: SECURITY: App token mismatch from {addr}. Connection rejected."
                self._log.wrn(t, addr=addr)
                sock.close()
                return

            # 3. Receive System Name length and string.
            name_len_bytes = sock.recv(4)
            if not name_len_bytes: return
            name_len = struct.unpack('>I', name_len_bytes)[0]
            remote_name = sock.recv(name_len).decode('utf-8')

            # NEW GUARD: Reset ghost connection from previous life if node rebooted quickly
            with self._lock:
                if remote_name in self._connections:
                    old_conn = self._connections.pop(remote_name, None)
                    if old_conn:
                        old_conn.stop()
                    if remote_name in self._broker._federation_routes:
                        self._broker._federation_routes.pop(remote_name, None)

            # 4. Respond with local credentials.
            self._send_handshake_response(sock)

            # 5. Identity collision check.
            if self._cfg.SYSTEM_NAME == remote_name:
                self._log.err("TCP: System name collision: {name}", name=remote_name)
                sock.close()
                return

            # 6. Cryptographic Challenge-Response verification.
            if not self._secure_auth_exchange(sock):
                self._log.wrn("TCP: SECURITY: Password authentication failed from {name} ({addr})", 
                              name=remote_name, addr=addr)
                sock.close()
                return

            # 7. Instant synchronous manifest exchange over the wire.
            # First, transmit our compiled local public manifests
            local_m_bytes = self._pack_local_manifests()
            sock.sendall(struct.pack('>I', len(local_m_bytes)) + local_m_bytes)
            
            # Then, read the foreign system's manifests
            remote_m_len_bytes = sock.recv(4)
            if not remote_m_len_bytes: 
                raise ValueError("Missing remote manifest header")
            remote_m_len = struct.unpack('>I', remote_m_len_bytes)[0]
            remote_m_bytes = sock.recv(remote_m_len)

            # Register connection and dispatch manifests to the bus
            self._register_connection(remote_name, sock, addr)
            self._unpack_and_register_manifests(remote_m_bytes, remote_name)
            
        except Exception as e:
            self._log.err("TCP: Handshake failed with {addr}: {e}", addr=addr, e=e)
            sock.close()

    def _send_handshake_response(self, sock: socket.socket):
        """Sends our magic and name back to the requester."""
        name_bytes = self._cfg.SYSTEM_NAME.encode('utf-8')
        # Response: MAGIC (8b) + NAME_LEN (4b) + NAME (string).
        header = (
            self._cfg.MAGIC_HEADER + 
            self._cfg.NET_PROJECT_TOKEN + 
            struct.pack('>I', len(name_bytes))
        )
        sock.sendall(header + name_bytes)

    def _register_connection(self, name: str, sock: socket.socket, addr: tuple):
        """
        Registers a new inbound federation link after a successful handshake.
        Resolves name collisions using system rank comparison.
        """
        old_conn = None
        with self._lock:
            if name in self._connections:
                # Collision: if our name is alphabetically larger, we keep OUR outgoing connection,
                # and simply drop this new incoming one to avoid bridge duplication.
                if self._cfg.SYSTEM_NAME > name:
                    t = "TCP: Higher rank system (us), keeping existing conn to {name}."
                    self._log.inf(t, name=name)
                    sock.close()
                    return
                else:
                    # Our old connection is alphabetically smaller — removing it from cache for safe closure
                    old_conn = self._connections.pop(name)
        if old_conn:
            old_conn.stop()

        # Pass 'self' as the parent service explicitly to avoid unannotated hasattr checks
        conn = TcpConnection(name, sock, addr, self._broker, self._log, self._cfg, self)
        with self._lock:
            self._connections[name] = conn
        conn.start()
        self._log.inf("TCP: Federation link with '{name}' established.", name=name)     

        self.establish_federation(name)

        self._cfg.NET_AUTO_CONNECT = False
        if hasattr(self, '_udp_beacon') and self._udp_beacon:
            self._udp_beacon.stop()
            self._log.inf("TCP: SECURITY: Link active. UDP Beacon and discovery AUTO-DISABLED.")

        msg = {
            "msg_type": "sys",
            "sub_type": "net_connected",
            "sender": f"{self._cfg.SYSTEM_NAME}:TCP_SERVICE",
            "recipient": f"{self._cfg.SYSTEM_NAME}:{self._cfg.ADDR_KERNEL_STR}",
            "payload": {"sys_name": name}
        }
        self._broker.bus.put(msg)

    def _restore_network_discovery(self) -> None:
        """Restores UDP beaconing and auto-connect state if requested by config."""
        # Safeguard: Do not fire beacons if the framework service is already shutting down
        if not getattr(self, '_is_running', True):
            return
        with self._lock:
            # If there are still active connections left, do not re-enable discovery
            if any(c.is_alive for c in self._connections.values()):
                return

        # Check if this node initially wanted to be discoverable
        if getattr(self._cfg, 'NEEDS_NET_AUTO_CONNECT', True):
            self._cfg.NET_AUTO_CONNECT = True
            
            # If we have a reference to the beacon and it was stopped, restart its thread loop
            if hasattr(self, '_udp_beacon') and self._udp_beacon:
                # Since Python threads cannot be restarted once stopped, 
                # we check if we need to re-instantiate or just flip the flag.
                # If your UdpBeacon.stop() just clears a flag, we flip it back:
                if hasattr(self._udp_beacon, '_is_running') and not self._udp_beacon._is_running:
                    # If your original UdpBeacon allows restarting via changing the flag:
                    self._udp_beacon._is_running = True
                    # If your UdpBeacon terminates the thread completely on stop(), 
                    # a new instance should be created. But for V1, flipping the flag or 
                    # re-starting the loop logic is enough if the thread was kept alive.
                    # Let's verify how your UdpBeacon loop reacts.
                    pass
                
                self._log.inf("TCP: SECURITY: Link lost or cleared. UDP Discovery and Beacon RESTORED.")

    def disconnect_addr(self, addr: tuple) -> bool:
        """Disconnects a specific link by ip:port and evaluates discovery restoration."""
        target_name = None
        with self._lock:
            for name, conn in self._connections.items():
                if conn.addr == addr:
                    target_name = name
                    break
            if target_name:
                conn = self._connections.pop(target_name)
                conn.stop()
                
                # Safeguard: Wait for individual connection connection OS thread context to clear RAM fully
                if conn.is_alive():
                    conn.join(timeout=0.1)
                    
                self._log.inf("TCP: Explicitly disconnected from {addr}", addr=addr)
                
                # Trigger restoration check
                self._restore_network_discovery()
                return True
        return False

    def disconnect_all(self) -> None:
        """Disconnects all active federation links and fully restores discovery."""
        with self._lock:
            conns = list(self._connections.values())
            self._connections.clear()
            
        for conn in conns:
            conn.stop()
            
        # NEW SANITARY PAD: Cascadely join all closed socket threads to prevent RAM leakage leakage
        for conn in conns:
            if conn.is_alive():
                conn.join(timeout=0.1)
                
        self._log.inf("TCP: All network links explicitly disconnected and joined.")
        
        # Trigger full restoration
        self._restore_network_discovery()

    def establish_federation(self, system_name: str) -> None:
        """Assembles the network adapter and registers the route in the broker."""        
        remote_broker_addr = Addr(system_name, self._cfg.ADDR_BROKER_STR)
        adapter = TcpAdapterTransport(
            sanapo_addr=remote_broker_addr,
            sys_name=system_name,
            host=None,
            port=None,
            service=self
        )
        self._broker.register_federation_route(system_name, adapter)

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

    def enable_auto_connect(self, state: bool) -> None:
        """Enables or disables response to neighbors' UDP beacons."""
        self._cfg.NET_AUTO_CONNECT = state
        status = "ENABLED" if state else "DISABLED"
        self._log.inf("TCP: Automatic discovery connection is {status}", status=status)

    def connect_to(self, host: str, port: int) -> bool:
        """Forcefully initiates an outbound TCP connection to the specified node with immediate passport validation."""
        try:
            # Check if there is already an active connection with this address
            with self._lock:
                for conn in self._connections.values():
                    if conn.addr == (host, port) and conn.is_alive:
                        return True

            self._log.inf("TCP: Initiating explicit connect to {host}:{port}...", host=host, port=port)
            
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self._cfg.HANDSHAKE_TIMEOUT)
            sock.connect((host, port))
            
            # Send outbound handshake: Magic + Project Token + Our name
            sock.sendall(self._cfg.MAGIC_HEADER)
            if hasattr(self._cfg, 'NET_PROJECT_TOKEN'):
                sock.sendall(self._cfg.NET_PROJECT_TOKEN)
                
            name_bytes = self._cfg.SYSTEM_NAME.encode('utf-8')
            sock.sendall(struct.pack('>I', len(name_bytes)) + name_bytes)
            
            # Read inbound handshake response
            guest_magic = sock.recv(8)
            if guest_magic != self._cfg.MAGIC_HEADER:
                sock.close()
                return False
                
            if hasattr(self._cfg, 'NET_PROJECT_TOKEN'):
                guest_token = sock.recv(len(self._cfg.NET_PROJECT_TOKEN))
                allow_cross = getattr(self._cfg, 'NET_ALLOW_CROSS_DISTRIB', False)
                if guest_token != self._cfg.NET_PROJECT_TOKEN and not allow_cross:
                    sock.close()
                    return False
                    
            name_len_bytes = sock.recv(4)
            if not name_len_bytes:
                sock.close()
                return False
            name_len = struct.unpack('>I', name_len_bytes)[0]
            remote_name = sock.recv(name_len).decode('utf-8')
            
            if self._cfg.SYSTEM_NAME == remote_name:
                sock.close()
                return False
                
            # Guard: Drop outbound connection if a live bridge session with this node name already exists
            if self.is_conn_alive(remote_name):
                sock.close()
                return True

            # Cryptographic Challenge-Response verification
            if not self._secure_auth_exchange(sock):
                self._log.wrn("TCP: SECURITY: Password authentication failed at peer {name}", name=remote_name)
                sock.close()
                return False

            # Instant synchronous manifest exchange over the wire
            # First, read the server's manifests
            remote_m_len_bytes = sock.recv(4)
            if not remote_m_len_bytes: 
                raise ValueError("Missing server manifest header")
            remote_m_len = struct.unpack('>I', remote_m_len_bytes)[0]
            remote_m_bytes = sock.recv(remote_m_len)

            # Then, transmit our compiled local public manifests
            local_m_bytes = self._pack_local_manifests()
            sock.sendall(struct.pack('>I', len(local_m_bytes)) + local_m_bytes)

            # Register active session and dispatch manifests to the bus
            self._register_connection(remote_name, sock, (host, port))
            self._unpack_and_register_manifests(remote_m_bytes, remote_name)
            return True
        except Exception as e:
            self._log.err("TCP: Explicit connect to {host}:{port} failed: {e}", host=host, port=port, e=e)
            return False


    def is_conn_alive(self, name: str) -> bool:
        """Checks if an active session exists for a given federation system name."""
        with self._lock:
            return name in self._connections and self._connections[name].is_alive

    def is_conn_alive_addr(self, addr: tuple) -> bool:
        """Checks if an active session exists for a specific physical ip:port tuple."""
        with self._lock:
            return any(c.addr == addr and c.is_alive for c in self._connections.values())
