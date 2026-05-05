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
        self.enum_reg = enum_reg  # for Frame converting
        
        # Internal bus for all outgoing messages from units/services
        self.bus: queue.Queue[Frame] = queue.Queue()
        
        # Local routes: {Addr: BaseAdapterTransport}
        self._local_routes: dict[Addr, BaseAdapterTransport] = {}
        
        # Federated routes: {SystemName: BaseAdapterTransport}
        self._federation_routes: dict[str, BaseAdapterTransport] = {}
        
        # Event subscribers: {EvtType: set[Addr]}
        self._subscribers: dict[any, set[Addr]] = {}
        
        # Link to network service for direct sends
        self._tcp_service: Optional[TcpService] = None

    def set_tcp_service(self, service: TcpService):
        """Link the broker to the network infrastructure."""
        self._tcp_service = service

    def register_local_route(self, addr: Addr, transport: BaseAdapterTransport):
        """Registers a unit within the current system process."""
        self._local_routes[addr] = transport
        self._log.inf(f"Local route registered for {addr}")

    def register_federation_route(self, system_name: str, transport: BaseAdapterTransport):
        """Registers a link to another sanapo instance."""
        self._federation_routes[system_name] = transport
        self._log.inf(f"Federation link to '{system_name}' active")

    def step(self) -> bool:
        """Process a slice of messages from the global bus."""
        processed = 0
        limit = self._cfg.U_BUS_READ_LIMIT
        
        while processed < limit:
            try:
                frame = self.bus.get_nowait()
                self._route_frame(frame)
                processed += 1
            except queue.Empty:
                break
            except Exception as e:
                self._log.crt(f"Routing failure: {e}")
                break
        return processed > 0

    def _route_frame(self, frame: Frame):
        """Logic for dispatching different message types."""
        # 1. EVENTS: Multicast to all interested parties
        if frame.msg_type == MsgType.EVT:
            targets = self._subscribers.get(frame.evt_type, set())
            for addr in targets:
                self._deliver(frame, addr)

        # 2. SYSTEM: Internal signaling and subscriptions
        elif frame.msg_type == MsgType.SYS:
            self._handle_system(frame)
            # System frames always reach the local Kernel
            self._deliver(frame, self._cfg.ADDR_KERNEL)

        # 3. COMMANDS / REPORTS: Direct delivery
        else:
            if not self._deliver(frame, frame.recipient):
                self._handle_unreachable(frame)

    def _deliver(self, frame: Frame, target_addr: Addr) -> bool:
        """Decides if the target is local or needs to be sent to federation."""
        
        # CASE A: Target is in our local process
        if target_addr.is_local(self._cfg.SYSTEM_NAME):
            transport = self._local_routes.get(target_addr)
            if transport:
                return transport.send(frame)
        
        # CASE B: Target is in another system
        else:
            fed_transport = self._federation_routes.get(target_addr.system)
            if fed_transport:
                # We forward the frame as-is (Native Tunneling)
                return fed_transport.send(frame)
        
        return False

    def _handle_system(self, frame: Frame):
        """Automated subscription management."""
        # SUB_SETUP (del all)
        if frame.sys_type == SysType.SUB_SETUP:
            for s_set in self._subscribers.values():
                s_set.discard(frame.sender)
            self._log.inf(f"Broker: Subscriptions reset for {frame.sender}")

        # SUB и SUB_SETUP (add)
        if frame.sys_type in [SysType.SUB, SysType.SUB_SETUP]:
            evts = frame.payload.get("evt_list", [])
            for e in evts:
                if e not in self._subscribers: 
                    self._subscribers[e] = set()
                self._subscribers[e].add(frame.sender)
        
        # UNSUB (del some)
        elif frame.sys_type == SysType.UNSUB:
            evts = frame.payload.get("evt_list", [])
            for e in evts:
                if e in self._subscribers: 
                    self._subscribers[e].discard(frame.sender)


    def _handle_unreachable(self, frame: Frame):
        """Auto-reject commands for missing addresses."""
        if frame.msg_type == MsgType.CMD:
            # Generate auto-report / Авто-отчет об отсутствии цели
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
