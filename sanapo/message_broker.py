# sanapo/message_broker.py
from __future__ import annotations
import queue
from typing import TYPE_CHECKING, Optional

from sanapo.enums import MsgType, SysType, RptType, RptReason
from sanapo.protocol import Frame

if TYPE_CHECKING:
    from sanapo.config import Config
    from sanapo.logger import Logger
    from sanapo.addr import Addr
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
        self._local_routes: dict[Addr, BaseAdapterTransport] = {}
        self._federation_routes: dict[str, BaseAdapterTransport] = {}
        self._addr_book: dict[str, Addr] = {}
        
        # Subscription registry: {EventEnum: {set of Subscriber Addresses}}
        self._subscribers: dict[any, set[Addr]] = {}
        self._tcp_service: Optional[TcpService] = None

    def set_tcp_service(self, service: TcpService):
        """Link the broker to the network infrastructure."""
        self._tcp_service = service

    def register_local_route(self, unit_name: str, transport: BaseAdapterTransport):
        """Registers a unit using unit name string."""
        addr_obj = self.get_addr(unit_name)
        self._local_routes[addr_obj] = transport
        self._log.inf(f"Local route registered for {addr_obj}")

    def register_federation_route(self, system_name: str, transport: BaseAdapterTransport):
        """Registers a link to another sanapo instance."""
        self._federation_routes[system_name] = transport
        self._log.inf(f"Federation link to '{system_name}' active")

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
                self._log.crt(f"Broker: Routing failure: {e}")
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
            self._deliver(frame, self._cfg.ADDR_KERNEL_STR)

        # 3. COMMANDS / REPORTS: Direct delivery
        else:
            if not self._deliver(frame, frame.recipient):
                self._handle_unreachable(frame)

    def _deliver(self, frame: Frame, target_addr: Addr) -> bool:
        """Handles physical delivery logic (Local vs Federation)."""
        # Case A: Internal delivery (Queue)
        if target_addr.is_local(self._cfg.SYSTEM_NAME):
            transport = self._local_routes.get(target_addr)
            if transport:
                return transport.send(frame)
        
        # Case B: External delivery (TCP/Federation)
        else:
            fed_transport = self._federation_routes.get(target_addr.system)
            if fed_transport:
                return fed_transport.send(frame)
        
        return False

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
                sender=self._cfg.ADDR_BROKER,
                recipient=frame.sender,
                rpt_type=RptType.CANT_DO,
                cmd_id=frame.cmd_id,
                reason=RptReason.NOT_IMPLEMENTED,
                payload={"text": f"Target {frame.recipient} unreachable"}
            )
            self._deliver(report, frame.sender)

    def get_addr(self, addr_str: str) -> Addr:
        """
        Normalizes and returns a singleton Addr object.
        Replaces local system name with 'LOCAL'.
        """
        temp_addr = Addr.from_str(addr_str)
        if not temp_addr: return None
        
        sys_part = temp_addr.system
        if sys_part == self._cfg.SYSTEM_NAME:
            sys_part = "LOCAL"
            
        cache_key = f"{sys_part}:{temp_addr.unit}"
        
        if cache_key not in self._addr_book:
            self._addr_book[cache_key] = Addr(unit=temp_addr.unit, system=sys_part)
            
        return self._addr_book[cache_key]