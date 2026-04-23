# sanapo/kernel.py
from __future__ import annotations
import time
import asyncio
import threading
from enum import Enum
from typing import Type
from queue import Queue, Empty
from typing import TYPE_CHECKING

from sanapo.enums import MsgType, RptType, SysType, ShutdownTier, ModuleType, ModuleAddressError
from sanapo.protocol import Frame
from sanapo.secretary import Secretary
from sanapo.logger import Logger
from sanapo.config import Config

if TYPE_CHECKING:
    from main import Tools
    from sanapo.config import Config

AddrClass = Type[Enum]
EvtTypeClass = Type[Enum]
CmdTypeClass = Type[Enum]
Addr = Enum
EvtType = Enum
CmdType = Enum

from enum import Enum
from typing import Type

class Kernel:
    def __init__(self,
            addr: Addr,
            addr_enum: AddrClass,
            evt_enum: EvtTypeClass,
            cmd_enum: CmdTypeClass,
    ) -> None:
        # Types validation
        enums = {"addr": addr_enum, "evt": evt_enum, "cmd": cmd_enum}
        for key, val in enums.items():
            if not isinstance(val, type) or not issubclass(val, Enum):
                t = f"sanapo.Kernel: expects '{key}_enum' an Enum class, but got {type(val)}"
                raise TypeError(t)
        
        # Addr validation
        if not isinstance(addr, addr_enum):
            t = f"sanapo.Kernel: 'addr' must be an instance of {addr_enum.__name__}, got {addr}"
            raise TypeError(t)
        
        self._addr_cls: AddrClass = addr_enum
        self._evt_cls: EvtTypeClass = evt_enum
        self._cmd_cls: CmdTypeClass = cmd_enum
        
        self._addr = addr        

        self._config: Config = Config()
        self._logger: Logger = Logger(self._addr)
        
        self._bus: Queue = Queue()
        self._queue_reg: dict[Addr, Queue] = {}
        self._subscribers_evt: dict[EvtType, set[Addr]] = {}
        self._subscribers_cmd: dict[CmdType, set[Addr]] = {}
        
        self._is_running: bool = True

        # Start/Shutdown Orchestration/Registrations
        self._last_join_check: float = 0
        self._units_registry: dict[Addr, dict[str, any]]
        self._active_units: set[Addr]
        self._is_shutting_down: bool = False
        self._shutdown_tiers: dict[ShutdownTier, list[Addr]] = {}
        self._current_tier_idx: int = 0
        self._shutdown_tracker: dict[Addr, dict[str, any]] = {} # {'status':str, 'deadline':float}
        self._tiers_order: list[ShutdownTier] = list(ShutdownTier)

    # --- Registrations ---

    def setup_module_env(self,
            addr: Addr,
            m_type: ModuleType,
            m_class: Type[any],
            tier: ShutdownTier,
            thread: threading.Thread | None = None,
            *args, **kwargs
        ) -> any:
        """
        Factory method: creates a module, its secretary (if needed), its logger, 
        binds them, and registers the module for the shutdown sequence.
        """
        logger = Logger(addr, self._config)
        secr = self._get_secr(addr) if m_type != ModuleType.SIGMA else None
        module = m_class(m_type, logger, secr, *args, **kwargs)
        if secr: # non-SIGMA
            secr.set_logger(logger)
            secr.set_module(module)
        self._shutdown_tiers.setdefault(tier, []).append(addr)
        self._units_registry[addr] = {
            "module": module,
            "type": m_type,
            "secr": secr,
            "tier": tier,
            "thread": thread,
            }
        self._active_units.add(addr)
        status = "registered" if secr else "standalone"
        t = f"Module {addr.name} created as {status} (Tier: {tier.name})."
        self._logger.inf(t)
        return module

    def _get_secr(self, addr: Addr) -> Secretary:
        if not isinstance(addr, Addr):
            text = f"sanapo.Kernel: Address '{addr}' is not defined in Addr."
            raise ModuleAddressError(text)
        if addr in self._queue_reg:
            text = f"sanapo.Kernel: Address '{addr}' is already registered by another module."
            raise ModuleAddressError(text)
        config = self._config
        outbox = self._bus
        inbox = Queue()
        self._queue_reg[addr] = inbox
        sec =  Secretary(addr, outbox, inbox, config)
        self._logger.inf(f"Secretary for {addr.name} registered and instantiated.")
        return sec
    
    def _addr_deregister(self, addr: Addr) -> None:
        """Final cleanup: wipes the address from all registries and subscriptions."""
        self._send_sys(SysType.ADDR_DEREGISTER, {"addr": addr})
        for sub_dict in [self._subscribers_evt, self._subscribers_cmd]:
            for listeners in sub_dict.values():
                listeners.discard(addr)
        self._queue_reg.pop(addr, None)
        self._active_units.discard(addr)

    # --- Start units ---

    def _start_unit(self, addr: Addr) -> None:
        """Starts a specific unit based on its ModuleType."""
        thread = unit_info.get('thread')
        unit_info = self._units_registry.get(addr)
        if not unit_info:
            self._logger.err(f"Start for module {Addr.name}, but register has not module")
            return
        
        m_type = unit_info.get('type')
        module = unit_info.get('module')
        secr = unit_info.get('secr')
        thread = unit_info.get('thread')

        if m_type == ModuleType.UTILITY:
            self._logger.inf(f"Unit {addr.name}: UTILITY mode, no start needed.")
            
        elif m_type in [ModuleType.SIGMA, ModuleType.MASTER]:
            self._logger.inf(f"Unit {addr.name}: Starting thread/loop (MASTER/SIGMA).")
            if thread and not thread.is_alive(): thread.start()
            module.start()
            self._active_units.add(addr)
            
        elif m_type in [ModuleType.ZOMBIE, ModuleType.TICKABLE]:
            if secr:
                self._logger.inf(f"Unit {addr.name}: Starting secretary loop.")
                secr.start()
                self._active_units.add(addr)

    def start_inactive_units(self) -> None:
        """
        Orchestrates the startup of all registered but currently inactive units.
        The sequence follows the hierarchical order defined in ShutdownTier.
        """
        # Iterating through tiers strictly in ascending order (CORE -> EXTENSION)
        for tier in self._tiers_order:
            # Getting the list of module addresses registered for this tier
            addrs_in_tier = self._shutdown_tiers.get(tier, [])
            
            # Skip to the next tier if this one is empty
            if not addrs_in_tier:
                continue

            self._logger.inf(f"Launching inactive units in Tier {tier.value}: {tier.name}")

            for addr in addrs_in_tier:
                # Launch the unit only if it is not already in the active set
                if addr not in self._active_units:
                    self._start_unit(addr)

            # Small delay between tiers to allow services to stabilize
            if hasattr(self._config, 'TIER_STARTUP_DELAY'):
                time.sleep(self._config.TIER_STARTUP_DELAY)

        self._logger.crt(f"Startup complete. Total active units: {len(self._active_units)}")


    # --- Stop units ---

    def _shutdown_initialization(self, sender: Addr | None = None) -> None:
        """Starts the tiered shutdown sequence."""
        if self._is_shutting_down: return
        self._is_shutting_down = True
        self._current_tier_idx = 0
        by = f" by {sender}" if sender else ""
        self._logger.inf(f"SHUTDOWN: System sequence initiated{by}")
        self._prepare_next_tier()

    def _prepare_next_tier(self) -> None:
        """Prepares the next group of modules for shutdown."""
        self._last_join_check = 0

        # If the tiers are over, stop Kernel
        if self._current_tier_idx >= len(self._tiers_order):
            self._stop()
            return

        # Get list of Addr by current tier
        tier = self._tiers_order[self._current_tier_idx]
        targets = self._shutdown_tiers.get(tier, [])
        
        # If list of Addr by current tier is empty - next tier
        active_targets = [a for a in targets if a in self._active_units]
        if not active_targets:
            self._current_tier_idx += 1
            self._prepare_next_tier()
            return

        # Start stopping for active Addr in tier (active Addr in list of Arrd by current tier)
        self._logger.inf(f"SHUTDOWN: Processing Tier [{tier.name}]")
        deadline_base = self._config.SHUTDOWN_TIMEOUT[tier]
        for addr in active_targets:
            self._shutdown_tracker[addr] = {
                'status': 'WAITING_SOFT_STOP',
                'deadline': time.perf_counter() + deadline_base
            }
            self._send_module_stop(addr, deadline_base)

    def _force_stop_unit(self, addr: Addr) -> None:
        """Hard stop for unit: stops secretary and deregisters."""
        unit_info = self._units_registry.get(addr)
        if not unit_info:
            self._logger.err(f"Forsed stop for module {Addr.name}, but register has not module")
            return

        m_type = unit_info['type']
        module = unit_info['module']
        secr = unit_info['secr']

        if m_type in [ModuleType.SIGMA, ModuleType.MASTER]:
            self._logger.inf(f"Unit {addr.name}: Starting thread/loop (MASTER/SIGMA).")
            module.stop()
            
        elif m_type in [ModuleType.ZOMBIE, ModuleType.TICKABLE]:
            if secr:
                self._logger.inf(f"Unit {addr.name}: Starting secretary loop.")
                secr.stop()
        if addr in self._shutdown_tracker:
            self._shutdown_tracker[addr]['status'] = 'WAITING_HURD_STOP'
        
            
        self._addr_deregister(addr)

    def _check_shutdown_progress(self) -> None:
        """Non-blocking check of shutdown status and thread cleanup."""
        if not self._is_shutting_down: return
        
        now = time.perf_counter()
        
        # Handling timeouts
        # Get list of expired addr and forced stop them
        expired = [a for a, info in self._shutdown_tracker.items() if now > info['deadline']]
        for addr in expired:
            self._logger.wrn(f"SHUTDOWN: Timeout for {addr.name}! Forcing stop.")
            self._force_stop_unit(addr)
            self._shutdown_tracker.pop(addr, None)

        # If the list of Addr by current tier is empty - next tier
        if not self._shutdown_tracker:
            self._current_tier_idx += 1
            self._prepare_next_tier()

    def _check_shutdown_progress(self) -> None:
        """Main check inside launch() loop during shutdown."""
        if not self._is_shutting_down: return
        
        now = time.perf_counter()

        # Handling timeouts
        # Get list of expired addr and forced stop them
        expired = [a for a, info in self._shutdown_tracker.items() if now > info['deadline']]
        for addr in expired:
            self._logger.wrn(f"SHUTDOWN: Timeout for {addr.name}! Forcing stop.")
            self._force_stop_unit(addr)
            self._shutdown_tracker.pop(addr, None)

        # Try join avive thread (one for SHUTDOWN_JOIN_INTERVAL)
        if now - self._last_join_check >= self._config.SHUTDOWN_JOIN_INTERVAL:
            self._last_join_check = now
            self._try_join_threads()

        # Take a snapshot of the tracker to safely delete elements
        if not self._shutdown_tracker:
            self._current_tier_idx += 1
            self._prepare_next_tier()

    def _try_join_threads(self) -> None:
        """Attempt to join alive threads without blocking the loop too much."""
        # Take a snapshot of the tracker to safely delete elements
        for addr, info in list(self._shutdown_tracker.items()):
            unit_info = self._units_registry.get(addr)
            thread = unit_info.get('thread') if unit_info else None

            if thread and thread.is_alive():
                # Micro-wait from config
                thread.join(timeout=self._config.SHUTDOWN_JOIN_TIMEOUT)
                
            # If after join (or if there was no join) the thread is dead, we clean it
            if not thread or not thread.is_alive():
                self._logger.inf(f"SHUTDOWN: Unit {addr.name} halted.")
                self._shutdown_tracker.pop(addr, None)
                self._addr_deregister(addr)

    def _unit_shutdown(self, addr: Addr, deadline: float | None = None) -> None:
        """Soft stop: Requesting unit to clean up and report HALTED."""
        if not deadline:
            tier = self._units_registry[addr]["tier"]
            deadline = deadline if deadline else self._config.UNIT_SHUTDOWN_TIMEOUT[tier]
        frame = Frame(
            msg_type=MsgType.SYSTEM,
            sender=self._addr,
            recipient=addr,
            sys_type=SysType.UNIT_SHUTDOWN,
            deadline=time.perf_counter() + deadline
        )
        self._bus.put_nowait(frame)

    def _unit_stop(self, addr: Addr) -> None:
        """Hard stop: Forcing immediate secretary/module halt."""
        frame = Frame(
            msg_type=MsgType.SYSTEM,
            sender=self._addr,
            recipient=addr,
            sys_type=SysType.UNIT_STOP
        )
        self._bus.put_nowait(frame)
        # TODO Thread ? 
        # Note: Thread join logic is handled in _check_shutdown_progress 
        # via _try_join_threads with Config.SHUTDOWN_JOIN_TIMEOUT

    def _on_unit_halted(self, addr: Addr) -> None:
        """Fast-track shutdown: Module confirmed it is dead."""
        if addr in self._shutdown_tracker:
            self._logger.inf(f"SHUTDOWN: {addr.name} reported HALTED. Accelerating tier.")
            self._shutdown_tracker.pop(addr)
            # TODO Thread ? 

    # --- Bus reading ---

    def _route_messages(self) -> None:
        """Main dispatcher loop: sorts and delivers all types of frames."""
        processed = 0
        while not self._bus.empty() and processed < self._config.BUS_READ_LIMIT:
            try:
                frame = self._bus.get_nowait()
            except Empty: break
            if not isinstance(frame, Frame):
                self._logger.crt(f"Object in Bus is not a Frame instance. Object: {frame}")
                continue
            processed += 1
            if frame.deadline and time.perf_counter() > frame.deadline:
                    self._logger.wrn(f"Deadline expired", frame, "MSD")
                    continue
            if frame.msg_type == MsgType.SYSTEM:
                self._handle_sys(frame)
            elif frame.msg_type == MsgType.COMMAND:
                self._handle_cmd(frame)
            elif frame.msg_type == MsgType.EVENT:
                self._handle_evt(frame)
            elif frame.msg_type == MsgType.REPORT:
                self._handle_rpt(frame)
        if processed >= self._config.THRESHOLD_BUS_OVERCROWDED:
            self._logger.wrn(f"Bus is overcrowded. QueueSize:{processed}")

    def _handle_cmd(self, frame: Frame) -> None:
        """Logic for COMMAND: Check registry and subscriber rights."""
        dest = frame.recipient
        # Check destination registration (Queue)
        if dest not in self._queue_reg:
            self._logger.wrn("Recipient not registered", frame, "MSD")
            self._send_rpt(frame, RptType.NO_REGISTRED_EXECUTOR)
            return
        # Check subscribers
        allowed_handlers = self._subscribers_cmd.get(frame.cmd_type, set())
        if dest not in allowed_handlers:
            self._logger.wrn("Recipient not subscribed to this CmdType", frame, "MSD")
            self._send_rpt(frame, RptType.NO_SUBSCRIBED_EXECUTOR)
            return
        self._queue_reg[dest].put_nowait(frame)

    def _handle_evt(self, frame: Frame) -> None:
        """Logic for EVENT: Multicast to all except sender."""
        subscribers = self._subscribers_evt.get(frame.evt_type, set())
        for addr in subscribers:
            # Echo-filter: don't send back to author
            if addr != frame.sender and addr in self._queue_reg:
                self._queue_reg[addr].put_nowait(frame)

    def _handle_rpt(self, frame: Frame) -> None:
        """Logic for REPORT: Standard delivery + shutdown intercept."""            
        # Standard delivery to recipient
        dest = frame.recipient
        if dest in self._queue_reg:
            self._queue_reg[dest].put_nowait(frame)

    def _handle_sys(self, frame: Frame) -> None:
        """Universal handler for system-level infrastructure."""
        sys_type = frame.sys_type
        sender = frame.sender

        if sys_type == SysType.APP_SHUTDOWN:
            self._shutdown_initialization(sender)
        
        elif sys_type == SysType.UNIT_HALTED:
            self._on_unit_halted(sender)

        elif sys_type == SysType.ADDR_DEREGISTER:
            self._addr_deregister(sender)

        elif sys_type in [SysType.UNIT_SLEEP, SysType.UNIT_WAKEUP]:
            # Simple pass-through to the specific secretary
            dest = frame.recipient
            if dest in self._queue_reg:
                self._queue_reg[dest].put_nowait(frame)

        elif sys_type in [SysType.SUB, SysType.UNSUB, SysType.SUB_SETUP]:
            self._handle_subscriptions(frame)

    def _handle_subscriptions(self, frame: Frame) -> None:
        sys_type, addr = frame.sys_type, frame.sender
        payload = frame.payload if isinstance(frame.payload, dict) else {}
        
        # If SETUP is a cleanup before updating
        if sys_type == SysType.SUB_SETUP:
            for d in [self._subscribers_evt, self._subscribers_cmd]:
                for s in d.values(): s.discard(addr)

        # We process both lists from one frame
        configs = [
            ("evt_list", self._subscribers_evt, self._evt_cls),
            ("cmd_list", self._subscribers_cmd, self._cmd_cls)
        ]
        
        action = "discard" if sys_type == SysType.UNSUB else "add"

        for key, target_dict, target_cls in configs:
            msg_list = payload.get(key, [])
            for msg_kind in msg_list:
                if isinstance(msg_kind, target_cls):
                    if action == "add":
                        target_dict.setdefault(msg_kind, set()).add(addr)
                    else:
                        target_dict.get(msg_kind, set()).discard(addr)

    # --- Kernel Loop ---

    def start(self) -> None:
        self._is_running = False
        self._loop()

    def stop(self) -> None:
        self._logger.inf("Kernel stopping")
        self._is_running = False

    def _loop(self) -> None:
        self._logger.inf("Kernel is started")
        tct = self._config.KERNEL_TICK_TCT
        while self._is_running:
            t_start = time.perf_counter()
            self._route_messages()
            if self._is_shutting_down:
                self._check_shutdown_progress()
            elapsed = time.perf_counter() - t_start
            if elapsed > tct:
                self._logger.wrn(f"TCT Overrun: {elapsed:.4f}s > {tct}s")
            else:
                time.sleep(tct - elapsed)
        self._logger.inf("Kernel is halted")

