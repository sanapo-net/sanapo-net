# sanapo/transport/services/tcp.py
from __future__ import annotations
import socket
import threading
import struct
import json
import os
import random
import time
import hashlib
from typing import TYPE_CHECKING

from sanapo.transport.adapters.tcp import TcpAdapterTransport
from sanapo.addr import Addr
from sanapo.enums import ConnState

if TYPE_CHECKING:
    from sanapo.config import Config
    from sanapo.logger import Logger
    from sanapo.message_broker import MessageBroker
    from sanapo.transport.services.udp import UdpBeacon

"""
tcp pakets types:
00 - connect-req
01 - token-meta-req
02 - token-meta-ack
03 - connect-ack
04 - connect-cls
05 - ping-req
06 - ping-ack
07 - meta-manifests
08 - meta-evt
09 - meta-cmd
10 - msg-sys
11 - msg-rpt
12 - msg-cmd
13 - msg-evt
14 - beacon
15 - connect-rej
"""

class TcpConnection(threading.Thread):
    """State‑machine driven TCP connection with unified header and explicit handshake."""

    def __init__(
        self,
        name: str,
        sock: socket.socket,
        addr: tuple,
        broker: MessageBroker,
        logger: Logger,
        config: Config,
        service: "TcpService",
        is_outbound: bool = False,
    ):
        super().__init__(name=f"TCP-{name}", daemon=True)
        self.remote_system_name: str = name
        self.sock: socket.socket = sock
        self.addr: Addr = addr
        self._broker: MessageBroker = broker
        self._log: Logger = logger
        self._cfg: Config = config
        self._service: "TcpService" = service
        self._is_outbound = is_outbound

        self.state: ConnState = ConnState.IDLE
        self._waiting_for: int | None = None
        self._wait_deadline: float = 0.0
        self._token: bytes | None = None
        self._last_rx: float = time.monotonic()
        self._last_tx: float = time.monotonic()
        self._alive: bool = True

        self._buffer = bytearray()
        self._header_len = 8 + 6 + 1 + 4

    # --- Public API ---

    def initiate_handshake(self) -> None:
        """Send connection request (type 00 connect-req)."""
        payload = json.dumps({"system_name": self._cfg.SYSTEM_NAME}).encode("utf-8")
        self.send_data_frame(0, payload)
        self.state = ConnState.SENT_CONN_REQ
        self._waiting_for = 1          # expect token-meta-req
        self._wait_deadline = time.monotonic() + self._cfg.CONN_WAIT_ANSW_MAX
        self._log.inf(
            "TCP: Connecting to {addr}: send connect-req",
            addr=self.addr,
        )

    # process_token_meta_req
    # old name: handle_server_handshake
    def handle_server_handshake(self, remote_system_name: str) -> None:
        """Server: start handshake by sending token-meta-req (type 01)."""
        self.remote_system_name = remote_system_name
        self._send_token_meta_req()

    def send_data_frame(self, msg_type: int, data: bytes) -> bool:
        """Encrypts (if needed), builds packet with unified header and sends it."""
        if len(data) > self._cfg.NET_MAX_MSG_SIZE:
            self._log.err(
                "TCP: Message too large ({size} bytes) for type {type}, dropping",
                size=len(data), type=msg_type
            )
            return False

        if self._cfg.NET_PASSWORD:
            data = self._xor_crypt(data)

        header = (
            self._cfg.MAGIC_HEADER
            + self._cfg.NET_PROJECT_TOKEN
            + struct.pack(">B", msg_type)
            + struct.pack(">I", len(data))
        )
        result = self._send_raw(header + data)
        if result:
            self._last_tx = time.monotonic()
        return result

    # --- Receive thread ---

    def run(self) -> None:
        self.sock.settimeout(0.5)
        while self._alive:
            try:
                data = self.sock.recv(4096)
                if not data:
                    self._close("recv_empty")
                    break
                self._last_rx = time.monotonic()
                self._buffer.extend(data)
                self._process_buffer()
            except socket.timeout:
                self._check_timeout()
                self._check_keepalive()
            except Exception as e:
                if self._alive:
                    self._log.err(
                        "TCP: Error on {name}: {e}", name=self.remote_system_name, e=e
                    )
                self._close("exception")
                break

    def _process_buffer(self) -> None:
        """Extract complete packets from the buffer."""
        while len(self._buffer) >= self._header_len:
            magic = self._buffer[0:8]
            token = self._buffer[8:14]
            if magic != self._cfg.MAGIC_HEADER or token != self._cfg.NET_PROJECT_TOKEN:
                self._log.crt(
                    "TCP: Protocol violation from {addr}", addr=self.addr
                )
                self._close("protocol_violation")
                return

            (msg_type,) = struct.unpack(">B", self._buffer[14:15])
            (length,) = struct.unpack(">I", self._buffer[15:19])

            if length > self._cfg.NET_MAX_MSG_SIZE:
                self._log.wrn(
                    "TCP: Packet too large ({len} bytes) from {addr}, discarding",
                    len=length, addr=self.addr
                )
                del self._buffer[: self._header_len + length]
                continue

            if len(self._buffer) < self._header_len + length:
                break

            payload = bytes(self._buffer[self._header_len : self._header_len + length])
            del self._buffer[: self._header_len + length]

            if self._cfg.NET_PASSWORD:
                payload = self._xor_crypt(payload)

            self._handle_packet(msg_type, payload)

    def _handle_packet(self, msg_type: int, data: bytes) -> None:
        """Dispatch incoming packet by type."""
        # 1. disconnect always processed
        if msg_type == 4:
            self._handle_disconnect(data)
            return

        self._last_rx = time.monotonic()

        # 2. keep-alive response (type 6)
        if msg_type == 6 and self._waiting_for == 6:
            self._waiting_for = None
            self._wait_deadline = 0.0
            return

        # 3. keep-alive request (type 5)
        if msg_type == 5:
            self.send_data_frame(6, b"")
            return

        # 4. check expected type during handshake
        if self._waiting_for is not None and msg_type != self._waiting_for:
            reason = "unexpected_packet_type"
            self._send_close(reason)
            self._close(reason)
            return

        # 5. dispatch
        if msg_type == 0:
            self._handle_conn_req(data)
        elif msg_type == 1:
            self._handle_token_meta_req(data)
        elif msg_type == 2:
            self._handle_token_meta_ack(data)
        elif msg_type == 3:
            self._handle_connect_ack(data)
        elif msg_type in (10, 11, 12, 13):
            self._handle_business(msg_type, data)
        elif msg_type == 15:
            self._handle_refuse(data)
        else:
            self._log.err(
                "TCP: Unknown packet type {type} from {name}",
                type=msg_type,
                name=self.remote_system_name,
            )

    # --- Packets processings ---

    def _handle_conn_req(self, data: bytes) -> None:
        """Incoming connect-req (type 00). Server side."""
        try:
            info = json.loads(data.decode("utf-8"))
            remote_name = info["system_name"]
        except Exception:
            self._close("invalid_conn_req")
            return

        if self.state != ConnState.IDLE:
            return
        self._log.inf(
            "TCP: Connecting to {sys}: recv connect-req",
            sys=remote_name,
        )
        self.handle_server_handshake(remote_name)

    # build_token_meta_req
    def _send_token_meta_req(self) -> None:
        """Send token and server metadata to client (type 01 token-meta-req)."""
        self._token = os.urandom(8)
        payload = {
            "token": self._token.hex(),
            "system_name": self._cfg.SYSTEM_NAME,
            "manifests": self._service._get_local_manifests_dict(),
            "events": self._service._get_local_event_names(),
            "commands": self._service._get_local_command_names(),
        }
        self.send_data_frame(1, json.dumps(payload).encode("utf-8"))
        self.state = ConnState.WAIT_TOKEN_RETURN
        self._waiting_for = 2          # expect token-meta-ack
        self._wait_deadline = time.monotonic() + self._cfg.CONN_WAIT_ANSW_MAX
        self._log.inf(
            "TCP: Connecting to {sys}: send token-meta-req",
            sys=self.remote_system_name,
        )

    # process_token_meta_req
    # old name: _handle_token
    def _handle_token_meta_req(self, data: bytes) -> None:
        """Client received token-meta-req (type 01). Process and reply with token-meta-ack."""
        try:
            payload = json.loads(data.decode("utf-8"))
            token = payload["token"]
            remote_name = payload.get("system_name")
            if not remote_name:
                manifests = payload.get("manifests", {})
                if manifests:
                    first_key = next(iter(manifests))
                    remote_name = first_key.split(":")[0]
                else:
                    raise ValueError("system_name not found in token-meta-req")
            self.remote_system_name = remote_name
        except Exception:
            self._close("invalid_token_meta_req")
            return

        self._log.inf(
            "TCP: Connecting to {sys}: recv token-meta-req",
            sys=self.remote_system_name,
        )

        self._service._on_got_system_data(
            self.remote_system_name,
            payload.get("manifests", {}),
            payload.get("events", []),
            payload.get("commands", []),
        )
        self._send_token_meta_ack(token)

    # build_token_meta_ack
    def _send_token_meta_ack(self, token_hex: str) -> None:
        """Send token back with client metadata (type 02 token-meta-ack)."""
        payload = {
            "token": token_hex,
            "system_name": self._cfg.SYSTEM_NAME,
            "manifests": self._service._get_local_manifests_dict(),
            "events": self._service._get_local_event_names(),
            "commands": self._service._get_local_command_names(),
        }
        self.send_data_frame(2, json.dumps(payload).encode("utf-8"))
        self.state = ConnState.WAIT_ACCEPT
        self._waiting_for = 3          # expect connect-ack
        self._wait_deadline = time.monotonic() + self._cfg.CONN_WAIT_ANSW_MAX
        self._log.inf(
            "TCP: Connecting to {sys}: send token-meta-ack",
            sys=self.remote_system_name,
        )

    # process_token_meta_ack
    # old name: _handle_token_return
    def _handle_token_meta_ack(self, data: bytes) -> None:
        """Server received token-meta-ack (type 02). Verify token, save client metadata."""
        try:
            payload = json.loads(data.decode("utf-8"))
            remote_token = bytes.fromhex(payload["token"])
            remote_name = payload.get("system_name")
            if not remote_name:
                manifests = payload.get("manifests", {})
                if manifests:
                    first_key = next(iter(manifests))
                    remote_name = first_key.split(":")[0]
                else:
                    raise ValueError("system_name not found in token-meta-ack")
            self.remote_system_name = remote_name
        except Exception:
            self._send_close("invalid_token_meta_ack")
            self._close("invalid_token_meta_ack")
            return

        if remote_token != self._token:
            self._send_close("token_mismatch")
            self._close("token_mismatch")
            return

        self._log.inf(
            "TCP: Connecting to {sys}: recv token-meta-ack",
            sys=self.remote_system_name,
        )

        self._service._on_got_system_data(
            self.remote_system_name,
            payload.get("manifests", {}),
            payload.get("events", []),
            payload.get("commands", []),
        )
        self._send_connect_ack()

    # build_connect_ack
    def _send_connect_ack(self) -> None:
        """Send empty connect-ack (type 03) to client."""
        self.send_data_frame(3, b'{}')
        self._log.inf(
            "TCP: Connecting to {sys}: send connect-ack",
            sys=self.remote_system_name,
        )
        self._on_established()

    # process_connect_ack
    # old name: _handle_accept
    def _handle_connect_ack(self, data: bytes) -> None:
        """Client received connect-ack (type 03). Handshake complete."""
        try:
            json.loads(data.decode("utf-8"))
        except Exception:
            self._close("invalid_connect_ack")
            return

        self._log.inf(
            "TCP: Connecting to {sys}: recv connect-ack",
            sys=self.remote_system_name,
        )
        self._on_established()

    def _handle_business(self, msg_type: int, data: bytes) -> None:
        """Business messages (types 10-13)."""
        try:
            raw_dict = json.loads(data.decode("utf-8"))
            self._broker.bus.put(raw_dict)
        except Exception as e:
            self._log.err(
                "TCP: Failed to decode business frame from {name}: {e}",
                name=self.remote_system_name,
                e=e,
            )

    def _handle_disconnect(self, data: bytes) -> None:
        """Disconnect notification (type 04)."""
        try:
            info = json.loads(data.decode("utf-8"))
            reason = info.get("reason", "remote")
        except Exception:
            reason = "remote"
        self._close(reason)

    def _handle_refuse(self, data: bytes) -> None:
        """Connection refused (type 15)."""
        try:
            info = json.loads(data.decode("utf-8"))
            reason = info.get("reason", "unknown")
        except Exception:
            reason = "unknown"
        self._log.wrn(
            "TCP: Connection refused by {name}: {reason}",
            name=self.remote_system_name,
            reason=reason,
        )
        self._close("refused")

    # --- Internal logic ---

    def _on_established(self) -> None:
        """Transition to ACTIVE state, notify service."""
        self.state = ConnState.ACTIVE
        self._waiting_for = None
        self._wait_deadline = 0.0
        self._log.inf(
            "TCP: Connection to {name} active", name=self.remote_system_name
        )
        self._service._on_connection_established(self)

    def _send_close(self, reason: str) -> None:
        """Send disconnect notification (type 04)."""
        payload = json.dumps({"reason": reason}).encode("utf-8")
        self.send_data_frame(4, payload)

    def _close(self, reason: str) -> None:
        """Close socket and clean up resources."""
        if self.state == ConnState.CLOSED:
            return
        self.state = ConnState.CLOSED
        self._alive = False
        try:
            self.sock.close()
        except Exception:
            pass
        self._service._on_connection_closed(self)
        self._log.inf(
            "TCP: Connection to '{name}' closed: {r}",
            name=self.remote_system_name,
            r=reason,
        )

    def stop(self) -> None:
        """Public stop method."""
        if self.state == ConnState.CLOSED:
            return
        self._send_close("local_initiative")
        self._close("local_stop")

    def _send_raw(self, data: bytes) -> bool:
        """Physical send."""
        try:
            self.sock.sendall(data)
            return True
        except Exception:
            return False

    def _check_timeout(self) -> None:
        """Check if waiting deadline has passed."""
        if self._wait_deadline > 0 and time.monotonic() > self._wait_deadline:
            self._send_close("timeout")
            self._close("timeout")

    def _check_keepalive(self) -> None:
        """Idle check and send ping (type 5) if needed."""
        if self.state != ConnState.ACTIVE or not self._cfg.CONN_KEEP_ALIVE:
            return
        now = time.monotonic()
        idle = now - max(self._last_rx, self._last_tx)
        if idle > self._cfg.CONN_KEEP_ALIVE_MAX + random.uniform(0, 5):
            self.send_data_frame(5, b"")
            self._waiting_for = 6
            self._wait_deadline = now + self._cfg.CONN_WAIT_ANSW_MAX

    # --- Encryption ---

    def _xor_crypt(self, data: bytes) -> bytes:
        """XOR encrypt/decrypt using SHA-256 of password."""
        password = self._cfg.NET_PASSWORD
        if isinstance(password, str):
            password = password.encode('utf-8')
        key = hashlib.sha256(password).digest()
        return bytes([b ^ key[i % len(key)] for i, b in enumerate(data)])


class TcpService(threading.Thread):
    """Network gateway. Manages listener, handshakes and federation routing."""

    def __init__(self, config: Config, broker: MessageBroker, logger: Logger):
        super().__init__(name="TcpService", daemon=True)
        self._cfg = config
        self._log = logger
        self._broker = broker
        self._udp_beacon: UdpBeacon | None = None

        self._is_running = False
        self._connections: dict[str, TcpConnection] = {}
        self._system_data: dict[str, dict[str, any]] = {}
        self._listen_sock: None | socket.socket = None
        self._lock = threading.Lock()

    # --- Public methods ---

    def run(self) -> None:
        self._is_running = True
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((self._cfg.HOST, self._cfg.TCP_PORT_DEFAULT))
            s.listen(5)
            self._listen_sock = s
            addr_str = f"{self._cfg.HOST}:{self._cfg.TCP_PORT_DEFAULT}"
            self._log.inf("TCP: Server listening on {addr}", addr=addr_str)

            while self._is_running:
                try: client_sock, addr = s.accept()
                except OSError: break
                if self._cfg.NET_ALLOWED_IPS and addr[0] not in self._cfg.NET_ALLOWED_IPS:
                    self._log.wrn("TCP: Blocked untrusted IP {ip}", ip=addr[0])
                    client_sock.close()
                    continue
                threading.Thread(target=self._inbound_handshake, args=(client_sock, addr), 
                                 daemon=True).start()
            self._listen_sock = None

    def shutdown(self):
        """Forcefully terminates the listening thread."""
        self._is_running = False
        if self._listen_sock:
            try:
                self._listen_sock.close()
            except Exception:
                pass

    def connect_to(self, host: str, port: int) -> bool:
        """Outbound connection with retries."""
        for attempt in range(3):
            try:
                with self._lock:
                    if not self._cfg.NET_MULTI_CONNECT_OUT:
                        for conn in self._connections.values():
                            if not conn._is_outbound:
                                continue
                            if conn.state != ConnState.CLOSED:
                                self._log.wrn(
                                    "TCP: Outbound multi-connect disabled, "
                                    "already have active outbound connection."
                                )
                                return False

                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(self._cfg.CONN_WAIT_ANSW_MAX)
                sock.connect((host, port))

                conn = TcpConnection(
                    name="pending",
                    sock=sock,
                    addr=(host, port),
                    broker=self._broker,
                    logger=self._log,
                    config=self._cfg,
                    service=self,
                    is_outbound=True,
                )
                conn.initiate_handshake()
                conn.start()

                deadline = time.monotonic() + self._cfg.CONN_WAIT_ANSW_MAX * 3
                while conn.state not in (ConnState.ACTIVE, ConnState.CLOSED):
                    if time.monotonic() > deadline:
                        conn._close("handshake_timeout")
                        break
                    time.sleep(0.1)

                if conn.state == ConnState.ACTIVE:
                    # Connection already added to _connections and route registered
                    # inside _on_connection_established, nothing to do here.
                    return True
                else:
                    delay = random.uniform(0, 5)
                    self._log.wrn(
                        "TCP: Connect attempt {att} to {host}:{port} failed, "
                        "retrying in {d:.1f}s...",
                        att=attempt + 1,
                        host=host,
                        port=port,
                        d=delay,
                    )
                    time.sleep(delay)
            except Exception as e:
                self._log.err(
                    "TCP: Connect attempt {att} error: {e}",
                    att=attempt + 1,
                    e=e,
                )
                time.sleep(random.uniform(0, 5))
        return False

    def send_to_system(self, system_name: str, msg_type: int, data: bytes) -> bool:
        with self._lock:
            conn = self._connections.get(system_name)
        if conn and conn.state == ConnState.ACTIVE:
            return conn.send_data_frame(msg_type, data)
        return False

    def send_to_addr(self, addr: tuple, msg_type: int, data: bytes) -> bool:
        with self._lock:
            for conn in self._connections.values():
                if conn.addr == addr and conn.state == ConnState.ACTIVE:
                    return conn.send_data_frame(msg_type, data)
        return False

    # --- Local manifests and enumerations ---

    def _get_local_manifests_dict(self) -> dict:
        return self._broker.get_public_manifests_dict()

    def _get_local_event_names(self) -> list[str]:
        return [e.name for e in self._broker.enum_reg.evt]

    def _get_local_command_names(self) -> list[str]:
        return [c.name for c in self._broker.enum_reg.cmd]

    # --- Inbound handshake (server) ---

    def _inbound_handshake(self, sock: socket.socket, addr: tuple) -> None:
        try:
            sock.settimeout(self._cfg.CONN_WAIT_ANSW_MAX)

            header = self._recv_exact(sock, 19)
            if not header:
                sock.close()
                return

            magic = header[0:8]
            token = header[8:14]
            if magic != self._cfg.MAGIC_HEADER or token != self._cfg.NET_PROJECT_TOKEN:
                self._log.wrn("TCP: Invalid magic/token from {addr}", addr=addr)
                sock.close()
                return

            (msg_type,) = struct.unpack(">B", header[14:15])
            (length,) = struct.unpack(">I", header[15:19])

            if msg_type != 0:
                self._log.wrn(
                    "TCP: Expected type 0, got {t} from {addr}", t=msg_type, addr=addr
                )
                sock.close()
                return

            data = self._recv_exact(sock, length)
            if data is None:
                sock.close()
                return

            try:
                info = json.loads(data.decode("utf-8"))
                remote_name = info["system_name"]
            except Exception:
                self._log.err("TCP: Invalid conn request from {addr}", addr=addr)
                sock.close()
                return

            if remote_name == self._cfg.SYSTEM_NAME:
                self._send_refuse_and_close(sock, "self_connect")
                return

            with self._lock:
                for conn in self._connections.values():
                    if (
                        conn.addr == addr
                        and conn.state == ConnState.SENT_CONN_REQ
                        and conn._is_outbound
                    ):
                        self._send_refuse_and_close(
                            sock, "simultaneous_connect"
                        )
                        return

                if not self._cfg.NET_MULTI_CONNECT_IN:
                    for conn in self._connections.values():
                        if (
                            not conn._is_outbound
                            and conn.state == ConnState.ACTIVE
                        ):
                            self._send_refuse_and_close(
                                sock, "multi_connect_disabled"
                            )
                            return

                if remote_name in self._connections:
                    old = self._connections.pop(remote_name)
                    old.stop()

            conn = TcpConnection(
                name=remote_name,
                sock=sock,
                addr=addr,
                broker=self._broker,
                logger=self._log,
                config=self._cfg,
                service=self,
                is_outbound=False,
            )
            conn.handle_server_handshake(remote_name)
            # Connection will be added to _connections when it becomes ACTIVE
            conn.start()

        except Exception as e:
            self._log.err(
                "TCP: Inbound handshake failed with {addr}: {e}", addr=addr, e=e
            )
            sock.close()

    def _recv_exact(self, sock: socket.socket, size: int) -> bytes | None:
        buf = bytearray()
        while len(buf) < size:
            try:
                chunk = sock.recv(size - len(buf))
                if not chunk:
                    return None
                buf.extend(chunk)
            except socket.timeout:
                return None
        return bytes(buf)

    def _send_refuse_and_close(self, sock: socket.socket, reason: str) -> None:
        try:
            payload = json.dumps({"reason": reason}).encode("utf-8")
            header = (
                self._cfg.MAGIC_HEADER
                + self._cfg.NET_PROJECT_TOKEN
                + struct.pack(">B", 15)
                + struct.pack(">I", len(payload))
            )
            sock.sendall(header + payload)
        except Exception:
            pass
        finally:
            sock.close()

    # --- Internal connection management ---

    def _on_connection_established(self, conn: TcpConnection) -> None:
        """Called when connection becomes ACTIVE. Registers route, adds to connections, manages beacon."""
        name = conn.remote_system_name
        with self._lock:
            # Add to connections (replacing any old one)
            if name in self._connections:
                old = self._connections.pop(name)
                old.stop()
            self._connections[name] = conn

        # Register federation route (this broadcasts net_ready)
        remote_broker_addr = Addr(name, self._cfg.ADDR_BROKER_STR)
        adapter = TcpAdapterTransport(remote_broker_addr, name, service=self)
        self._broker.register_federation_route(adapter, self._system_data[name])

        if not self._cfg.NET_MULTI_CONNECT_OUT and self._udp_beacon:
            self._udp_beacon._is_running = False
            self._log.inf("TCP: Beacon stopped (single outbound connection established)")

    def _on_connection_closed(self, conn: TcpConnection) -> None:
        """Called when connection is closed."""
        with self._lock:
            if self._connections.get(conn.remote_system_name) == conn:
                del self._connections[conn.remote_system_name]

        self._restore_network_discovery()

        msg_disconnect = {
            "msg_type": "sys",
            "sub_type": "net_disconnected",
            "sender": f"{self._cfg.SYSTEM_NAME}:TCP_SERVICE",
            "recipient": f"{self._cfg.SYSTEM_NAME}:{self._cfg.ADDR_KERNEL_STR}",
            "payload": {"sys_name": conn.remote_system_name},
        }
        self._broker.bus.put(msg_disconnect)

    def _on_got_system_data(self, system_name, manifests: dict, events: list, commands: list) -> None:
        """Temporarily store remote system's metadata until connection is established."""
        data: dict[str, any] = {}
        data["manifests"] = manifests
        data["events"] = events
        data["commands"] = commands
        self._system_data[system_name] = data

    def _restore_network_discovery(self) -> None:
        """Restart UDP beacon if no active connections."""
        if not self._is_running:
            return
        with self._lock:
            if any(c.state == ConnState.ACTIVE for c in self._connections.values()):
                return
        if self._cfg.NET_BEACON and self._udp_beacon:
            self._udp_beacon._is_running = True
            self._log.inf("TCP: Network discovery RESTORED.")

    # --- Manual control utilities ---

    def disconnect_addr(self, addr: tuple) -> bool:
        with self._lock:
            for conn in list(self._connections.values()):
                if conn.addr == addr:
                    conn.stop()
                    return True
        return False

    def disconnect_all(self) -> None:
        with self._lock:
            conns = list(self._connections.values())
            self._connections.clear()
        for c in conns:
            c.stop()
            if c.is_alive():
                c.join(timeout=0.5)
        self._restore_network_discovery()

    def is_conn_alive(self, name: str) -> bool:
        with self._lock:
            conn = self._connections.get(name)
            return conn is not None and conn.state == ConnState.ACTIVE

    def is_conn_alive_addr(self, addr: tuple) -> bool:
        with self._lock:
            return any(
                c.addr == addr and c.state == ConnState.ACTIVE
                for c in self._connections.values()
            )

    def enable_auto_connect(self, state: bool) -> None:
        """Legacy method – sets auto-connect by beacon flag."""
        self._cfg.NET_AUTO_CONNECT_BY_BEACON = state
        self._log.inf(
            "TCP: Auto-connect by beacon {status}",
            status="ENABLED" if state else "DISABLED",
        )