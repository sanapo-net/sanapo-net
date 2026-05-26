# sanapo/message_broker.py
from __future__ import annotations
import queue
import threading
from typing import TYPE_CHECKING, Optional

from sanapo.enums import MsgType, SysType, RptType, RptReason
from sanapo.protocol import Frame
from sanapo.addr import Addr

if TYPE_CHECKING:
    from sanapo.config import Config
    from sanapo.logger import Logger
    from sanapo.enums import EnumRegistry
    from sanapo.transport.adapters import BaseAdapterTransport
    from sanapo.transport.services.tcp import TcpService

class MessageBroker:
    """
    Core Router of sanapo framework. 
    Manages local deliveries, event subscriptions, and federated system bridges.
    """
    def __init__(self, config: Config, logger: Logger, enum_reg: EnumRegistry):
        self._cfg = config
        self._log = logger
        self.enum_reg = enum_reg  # Registry for fast frame reconstruction
        
        # Internal bus for all outgoing messages from units/services
        self.bus: queue.Queue[Frame | dict] = queue.Queue()
        
        # Routing tables
        self._local_routes: dict[str, BaseAdapterTransport] = {}
        self._federation_routes: dict[str, BaseAdapterTransport] = {}
        self._addr_book: dict[str, Addr] = {}
        
        # Subscription registry: {EventEnum: {set of Subscriber Addresses}}
        self._subscribers: dict[any, set[Addr]] = {}
        self._tcp_service: Optional[TcpService] = None
        self.addr = Addr(config.SYSTEM_NAME, config.ADDR_BROKER_STR)
        self._addr_lock = threading.Lock()

    def set_tcp_service(self, service: TcpService):
        """Link the broker to the network infrastructure."""
        self._tcp_service = service

    def register_local_route(self, transport: BaseAdapterTransport):
        """Registers a local route using the address already stored in the transport."""
        addr_str = transport.sanapo_addr.unit
        self._local_routes[addr_str] = transport
        self._log.inf("BROKER: unit {addr} is registred as local", addr=addr_str)

    def register_federation_route(self, system_name: str, transport: BaseAdapterTransport):
        """Registers a link to another sanapo instance."""
        self._federation_routes[system_name] = transport
        self._log.inf("Federation link to '{name}' active", name=system_name)

    def step(self) -> bool:
        """Process a slice of messages from the global bus."""
        processed = 0
        limit = self._cfg.BROKER_BUS_READ_LIMIT
        
        while processed < limit:
            try:
                data = self.bus.get_nowait()
                self._route_frame(data)
                processed += 1
            except queue.Empty:
                break
            except Exception as e:
                self._log.crt("BROKER: Routing failure: {e}", e=e)
                break
        return processed > 0

    def _route_frame(self, data: Frame | dict):
        """Dispatches messages. Reconstructs light frame if input is a dict."""
        # Fast "re-wrapping" of network dicts into light Frame objects.
        # Passing self (broker) to resolve singleton Addr objects.
        frame = data if isinstance(data, Frame) else Frame.from_dict_light(data, self.enum_reg,self)

        # 1. EVENTS: Multicast to all interested parties
        if frame.msg_type == MsgType.EVT:
            targets = self._subscribers.get(frame.evt_type, set())
            for addr in targets:
                self._deliver(frame, addr)

        # 2. SYSTEM: Internal signaling and subscriptions
        elif frame.msg_type == MsgType.SYS:
            self._handle_system(frame)
            # Deliver to legitimate Addr object instead of clean config string
            self._deliver(frame, self._cfg.ADDR_KERNEL)


        # 3. COMMANDS / REPORTS: Direct delivery
        else:
            if not self._deliver(frame, frame.recipient):
                self._handle_unreachable(frame)

    def _deliver(self, frame: Frame, target_addr: Addr) -> bool:
        """Handles physical delivery logic (Local vs Federation)."""
        # Case A: Internal delivery (Queue)
        if target_addr.is_local(self._cfg.SYSTEM_NAME):
            transport = self._local_routes.get(target_addr.unit)
            if transport:
                return transport.send(frame)
        
        # Case B: External delivery (TCP/Federation)
        else:
            fed_transport = self._federation_routes.get(target_addr.system)
            if fed_transport:
                return fed_transport.send(frame)
        
        return False
    
    def broadcast_sys_message(self, sys_type: SysType, payload: dict) -> None:
        """Clones and delivers a system message to all currently registered local units."""
        for unit_name, transport in self._local_routes.items():
            if unit_name == self._cfg.ADDR_KERNEL_STR: 
                continue
                
            msg = {
                "msg_type": "sys",
                "sub_type": sys_type.value if hasattr(sys_type, 'value') else str(sys_type),
                "sender": f"{self._cfg.SYSTEM_NAME}:BROKER",
                "recipient": f"{self._cfg.SYSTEM_NAME}:{unit_name}",
                "payload": payload
            }
            # NATIVE USE: We use the framework's native send() method to push frames safely
            if hasattr(transport, 'send'):
                transport.send(msg)

    def _handle_system(self, frame: Frame):
        """Manages dynamic event subscriptions."""
        # Full reset for SUB_SETUP
        if frame.sys_type == SysType.SUB_SETUP:
            for s_set in self._subscribers.values():
                s_set.discard(frame.sender)

        # Add subscriptions for SUB and SUB_SETUP
        if frame.sys_type in [SysType.SUB, SysType.SUB_SETUP]:
            evts = frame.payload.get("evt_list", [])
            for e in evts:
                # Convert raw payload string/int back to Enum using registry
                e_enum = self.enum_reg.evt(e)
                self._subscribers.setdefault(e_enum, set()).add(frame.sender)
        
        # Target removal for UNSUB
        elif frame.sys_type == SysType.UNSUB:
            evts = frame.payload.get("evt_list", [])
            for e in evts:
                e_enum = self.enum_reg.evt(e)
                if e_enum in self._subscribers: 
                    self._subscribers[e_enum].discard(frame.sender)

    def _handle_unreachable(self, frame: Frame):
        """Generates auto-reports for failed command deliveries."""
        if frame.msg_type == MsgType.CMD:
            report = Frame(
                msg_type=MsgType.RPT,
                sender=self.addr,
                recipient=frame.sender,
                rpt_type=RptType.CANT_DO,
                cmd_id=frame.cmd_id,
                reason=RptReason.NOT_IMPLEMENTED,
                payload={"text": f"Target {frame.recipient} unreachable"}
            )
            self._deliver(report, frame.sender)

    def _normalize_str(self, addr_str: str) -> str:
        """Helper to ensure the address always has a system prefix."""
        if not addr_str: return ""
        return addr_str if ":" in addr_str else f"{self._cfg.SYSTEM_NAME}:{addr_str}"

    def find_addr(self, addr_str: str) -> Addr | None:
        """Only looks up existing addresses in the registry."""
        full_str = self._normalize_str(addr_str)
        if not full_str: return None
        with self._addr_lock:
            return self._addr_book.get(full_str)

    def ensure_addr(self, addr_str: str) -> Addr | None:
        """Returns an existing Addr or creates a new one if not found."""
        full_str = self._normalize_str(addr_str)
        if not full_str: return None
        with self._addr_lock:
            if full_str not in self._addr_book:
                temp = Addr.from_str(full_str)
                self._addr_book[full_str] = Addr(temp.system, temp.unit)
            return self._addr_book[full_str]

    def create_addr(self, addr_str: str) -> Addr | None:
        """Attempts to register a NEW unique address."""
        full_str = self._normalize_str(addr_str)
        with self._addr_lock:
            if full_str in self._addr_book:
                return None
        return self.ensure_addr(full_str)

    def deregister_addr(self, addr: Addr) -> bool:
        """Removes an address reference from the internal cache book."""
        cache_key = f"{addr.system}:{addr.unit}"
        with self._addr_lock:
            del_addr = self._addr_book.pop(cache_key, None)
        return del_addr is not None
