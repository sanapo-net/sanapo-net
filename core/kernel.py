# core/kernel.py
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from main import Tools

import asyncio
from queue import Queue, Empty
import time

from core.enums import Addr, MsgType, CmdType, EvtType, RptType, SysType, ShutdownTier
from core.enums import AddressBusyError, UnknownAddressError
from core.protocol import Frame
from core.secretary import Secretary
from core.config import Config

class Kernel:
    def __init__(self, tools: Tools) -> None:
        self._tools: Tools = tools
        self._config: Config = Config()
        
        self._is_running: bool = True

        self._bus: Queue = Queue()
        self._queue_reg: dict[Addr, Queue] = {}
        self._subscribers_evt: dict[EvtType, set[Addr]] = {}
        self._subscribers_cmd: dict[CmdType, set[Addr]] = {}
        
        self._module_reg: dict[Addr, any] = {}
        
        # Shutdown Orchestration
        self._is_shutting_down: bool = False
        self._shutdown_tiers: dict[ShutdownTier, list[Addr]] = {}
        self._current_tier_idx: int = 0
        self._shutdown_tracker: dict[Addr, dict[str, any]] = {} # {'status':str, 'deadline':float}
        # Order of execution
        self._tiers_order: list[ShutdownTier] = [
            ShutdownTier.LOGIC, 
            ShutdownTier.DATA, 
            ShutdownTier.INFRA
        ]

        self._tick_counter: int = 0
        self._ticks_lookup: set = (
            (240, EvtType.TICK_120),
            (48,  EvtType.TICK_24),
            (16,  EvtType.TICK_8),
            (8,   EvtType.TICK_4),
            (4,   EvtType.TICK_2),
            (2,   EvtType.TICK_1),
        )
        
    # --- Registrations ---

    def _get_secr(self, addr: Addr) -> Secretary:
        if not isinstance(addr, Addr):
            raise UnknownAddressError(f"Address '{addr}' is not defined in Addr enum.")
        if addr in self._queue_reg:
            raise AddressBusyError(f"Address '{addr}' is already registered by another module.")
        config = self._tools.config
        outbox = self._bus
        inbox = Queue()
        self._queue_reg[addr] = inbox
        sec =  Secretary(addr, outbox, inbox, config)
        text = f"[Kernel] Secretary for module {addr.name} registered and instantiated."
        self._send_evt(EvtType.LOG, {"text": text})
        return sec
    
    def registration(self,
            addr: Addr,
            module_class: type,
            tier: ShutdownTier,
            *args, **kwargs
        ) -> any:
        """
        Factory method: creates a module, its secretary, binds them, 
        and registers the module for the shutdown sequence.
        """
        secr = self._get_secr(addr)
        module_instance = module_class(self._tools, secr, *args, **kwargs)
        secr.set_module(module_instance)
        self._module_reg[addr] = module_instance
        if tier not in self._shutdown_tiers:
            self._shutdown_tiers[tier] = []
        self._shutdown_tiers[tier].append(addr)
        
        text = f"[Kernel] Module {addr.name} registered (Tier: {tier.name})."
        self._send_evt(EvtType.LOG, {"text": text})
        print(text)
        
        return module_instance

    def _addr_deregister(self, addr: Addr) -> None:
        """Final cleanup: wipes the address from all registries and subscriptions."""
        # Delete addr from subscribers
        for sub_dict in [self._subscribers_evt, self._subscribers_cmd]:
            for listeners in sub_dict.values():
                listeners.discard(addr)
        # Delete Queue of module by addr
        self._queue_reg.pop(addr, None)
        # Send event
        self._send_evt(EvtType.EVT_ADDR_DEREGISTER, {"addr":addr})

    # --- Ticks & MsgChekings---

    def _check_and_run_ticker(self) -> None:
        now = time.time()
        if now >= self._next_tick_time:
            self._ticker()
            self._next_tick_time = now + 0.5 

    def _ticker(self) -> None:
        """Heartbeat generator. RTT-ticks always go BEFORE Calendar-ticks."""
        self._tick_counter += 1
        payload = {"tick_id": self._tick_counter}
        sent_rtt = False

        # Find the "biggest" tick
        for steps, evt_type in self._ticks_lookup:
            if self._tick_counter % steps == 0:
                self._send_evt(evt_type, payload)
                sent_rtt = True
                break

        # or just tick 0.5
        if not sent_rtt:
            self._send_evt(EvtType.TICK_05, payload)
        now_10m = (int(time.time()) // 600) * 600
        if now_10m > self._last_10m_ts:
            self._last_10m_ts = now_10m
            self._send_evt(EvtType.TICK_10M, {"time": now_10m})

    def _system_msg_handler(self, frame: Frame) -> None:
        """Universal handler for all subscriptions and deregistrations."""
        # APP_STOP
        if frame.sys_type == SysType.APP_STOP:
            self._shutdown_initialization()
            return

        # ADDR_DEREGISTER
        if sys_type == SysType.ADDR_DEREGISTER:
            self._addr_deregister(frame.sender)
        
        # [OTHER]
        addr = frame.sender
        sys_type = frame.sys_type
        # Mapping system types to internal subscriber dictionaries
        target_map: dict[SysType, set[callable, str]] = {
            SysType.SUB_EVT: (self._subscribers_evt, "add"),
            SysType.UNSUB_EVT: (self._subscribers_evt, "discard"),
            SysType.SUB_EVT_SETUP: (self._subscribers_evt, "setup"),
            
            SysType.SUB_CMD: (self._subscribers_cmd, "add"),
            SysType.UNSUB_CMD: (self._subscribers_cmd, "discard"),
            SysType.SUB_CMD_SETUP: (self._subscribers_cmd, "setup"),
        }
        # Checkings
        if sys_type in list(target_map.keys()):
            err = ""
            if not isinstance(frame.payload, dict):
                err = "payload is not dict"
            elif "list" not in frame.payload:
                err = "payload has not key 'list'"
            elif not isinstance(frame.payload["list"], list):
                err = "payload['list'] is not list"
            if err:
                text = f"[KERNEL]: SysType.{sys_type}:{err}"
                self._send_evt(EvtType.ERR_LOGIC, {"text":text})
            else:
                msg_sub_types = frame.payload["list"]
                sub_dict, action = target_map[sys_type]
                
                # if SETUP — del address from everyone msg_sub_types
                if action == "setup":
                    for s in sub_dict.values(): s.discard(addr)
                    action = "add" # after just add adress to target msg_sub_types

                # Appy action (add or discard) to everyone msg_sub_type from payload
                for msg_sub_type in msg_sub_types:
                    if action == "add":
                        sub_dict.setdefault(msg_sub_type, set()).add(addr)
                    else:
                        sub_dict.get(msg_sub_type, set()).discard(addr)
    
    def _route_messages(self) -> None:
        """
        Main mail sorter (Main Thread).
        Processes the incoming _bus and distributes messages to module inboxes.
        """
        now = time.perf_counter()
        q_size = self._bus.qsize()

        # Overcrowd checking. Once every 1 second send event if the _bus is overcrowded.
        if q_size > self._config.BUS_READ_LIMIT:
            if now - self._last_overcrowded_alert > 1.0:
                self._send_evt(EvtType.BUS_IS_OVERCROWDED, {"text":f"Current _bus size: {q_size}"})
                self._last_overcrowded_alert = now

        # Message parsing cycle
        processed_count = 0
        try:
            while not self._bus.empty() and processed_count < self._config.BUS_READ_LIMIT:
                frame = self._bus.get_nowait()
                if not isinstance(frame, Frame):
                    text = "[KERNEL]: APPLogicError: into the Bus is not Frame type object"
                    self._send_evt(EvtType.ERR_LOGIC, {"text": text})
                    break
                processed_count += 1

                # SYSTEM message
                if frame.msg_type == MsgType.SYSTEM:
                    self._system_msg_handler(frame)
                    break

                # COMMAND message
                elif frame.msg_type == MsgType.COMMAND:
                    dest = frame.recipient
                    if dest in self._queue_reg:
                        # Find address-set in the dict of cmd subscribers
                        allowed_handlers = self._subscribers_cmd.get(frame.cmd_type, set())
                        if dest not in allowed_handlers:
                            # Executor exists, but it not subscribed for this CmdType
                            # NO_SUBSCRIBED_EXECUTOR
                            self._send_rpt(frame, RptType.NO_SUBSCRIBED_EXECUTOR)
                            break
                        # Executor exists and is subscribed - > send cmd
                        self._queue_reg[dest].put_nowait(frame)
                    else:
                        # NO_REGISTRED_EXECUTOR
                        self._send_rpt(frame, RptType.NO_REGISTRED_EXECUTOR)
                        break

                # REPORTS message
                elif frame.msg_type == MsgType.REPORT:
                    # SHUTDOWN LOGIC: Intercept reports if app-closing
                    if self._is_shutting_down and frame.cmd_id.startswith("stop_"):
                        self._handle_shutdown_report(frame)
                    # other reports
                    dest = frame.recipient
                    if dest in self._queue_reg:
                        self._queue_reg[dest].put_nowait(frame)

                # EVENT message
                elif frame.msg_type == MsgType.EVENT:
                    # Find subscribers-set in the dict of event subscribers
                    subscribers = self._subscribers_evt.get(frame.evt_type, set())
                    for addr in subscribers:
                        # Dont send event to autor
                        if addr != frame.sender and addr in self._queue_reg:
                            self._queue_reg[addr].put_nowait(frame)
        except Empty:
            pass
        except Exception as e:
            print(f"[ERROR] Routing failed: {e}")

    # --- Messegers ---

    def _send_evt(self, type: EvtType, payload: dict[str, any]) -> None:
        frame=Frame(MsgType.EVENT, Addr.KERNEL, evt_type=type, payload=payload)
        self._bus.put_nowait(frame)

    def _send_rpt(self, cmd:Frame, type:RptType) -> None:
        commander = cmd.sender
        cmd_id = cmd.cmd_id
        text = f"From: {cmd.sender} To: {commander} Type: {cmd.msg_type} "
        text += f"SubType: {cmd.cmd_type or cmd.rpt_type or 'None'} cmd_id: {cmd_id}"
        p = {"text":text}
        rpt = Frame(MsgType.REPORT, Addr.KERNEL, rpt_type=type, cmd_id=cmd_id, payload=p)
        self._bus.put_nowait(rpt)

    def _send_module_stop(self, target: Addr, deadline: float | None = None) -> None:
        """Command to module: STOP module"""
        if target in self._queue_reg:
            if deadline is None:
                deadline = self._tools.config.get_deadline_dur(CmdType.MODULE_STOP)
            frame = Frame(
                msg_type=MsgType.COMMAND,
                sender=Addr.KERNEL,
                recipient=target,
                cmd_type=CmdType.MODULE_STOP,
                cmd_id=f"stop_{int(time.time())}",
                deadline=time.perf_counter() + deadline,
                payload={}
            )
            self._bus.put_nowait(frame)
        else:
            text = f"[KERNEL]: try send MODULE_STOP to non registred module"
            self._send_rpt(EvtType.ERR_LOGIC, {"text": text})

    def _send_secr_stop(self, target: Addr) -> None:
        """System message to secretary: STOP secretary"""
        frame = Frame(
            msg_type=MsgType.SYSTEM,
            sender=Addr.KERNEL,
            recipient=target,
            sys_type=SysType.SECR_STOP
        )
        self._bus.put_nowait(frame)

    # --- Main ---
    def _shutdown_initialization(self) -> None:
        """Starts the tiered shutdown process."""
        if self._is_shutting_down: return
        self._is_shutting_down = True
        
        print(f"\n[KERNEL] !!! SHUTDOWN INITIATED !!!")
        self._send_evt(EvtType.LOG, {"text": "System shutdown sequence started."})
        
        self._current_tier_idx = 0
        self._prepare_next_tier()

    def _prepare_next_tier(self) -> None:
        """Prepares and triggers the next shutdown group."""
        if self._current_tier_idx >= len(self._tiers_order):
            self.stop() # No more tiers, stop the Kernel
            return

        tier = self._tiers_order[self._current_tier_idx]
        targets = self._shutdown_tiers.get(tier, [])

        if not targets:
            self._current_tier_idx += 1
            self._prepare_next_tier()
            return

        print(f"[KERNEL] [SHUTDOWN] Moving to {tier.name}...")
        
        # Default deadline from config or 5s
        base_deadline = 5.0 
        
        for addr in targets:
            self._shutdown_tracker[addr] = {
                'status': 'WAITING', 
                'deadline': time.perf_counter() + base_deadline
            }
            self._send_module_stop(addr, base_deadline)

    def _handle_shutdown_report(self, frame: Frame) -> None:
        """Processes reports specifically for stop commands."""
        addr = frame.sender
        if addr not in self._shutdown_tracker: return

        if frame.rpt_type == RptType.INTO_WORK:
            self._shutdown_tracker[addr]['status'] = 'INTO_WORK'
            
        elif frame.rpt_type in [RptType.DONE, RptType.CANT_DO]:
            # DONE or NOT_IMPLEMENTED — we don't care, it's a finish for us
            self._shutdown_tracker.pop(addr)
            
        elif frame.rpt_type == RptType.TIME_EXTENSION_REQUEST:
            if frame.time_ext_req:
                self._shutdown_tracker[addr]['deadline'] += frame.time_ext_req
                print(f"[KERNEL] [SHUTDOWN] {addr.name} requested +{frame.time_ext_req}s")

    def _check_shutdown_progress(self) -> None:
        """Monitors current tier progress and timeouts"""
        if not self._is_shutting_down: return

        # Check for expired deadlines
        now = time.perf_counter()
        expired = [addr for addr, info in self._shutdown_tracker.items() if now > info['deadline']]
        
        for addr in expired:
            print(f"[KERNEL] [SHUTDOWN] Timeout for {addr.name}! Forcing SecrStop.")
            self._shutdown_tracker.pop(addr)
            # We don't wait for them anymore

        # If current tier is empty, move to next
        if not self._shutdown_tracker:
            # Send SECR_STOP to all secretaries of the finished tier
            finished_tier = self._tiers_order[self._current_tier_idx]
            for addr in self._shutdown_tiers.get(finished_tier, []):
                self._send_secr_stop(addr)
            
            self._current_tier_idx += 1
            self._prepare_next_tier()



    def stop(self) -> None:
        print("[Kernel] Shutdown initiated...")
        self._is_running = False

    async def launch(self) -> None:
        """core starter"""
        print("[Kernel] Running...")
        while self._is_running:
            self._route_messages()
            self._check_and_run_ticker()
            if self._is_shutting_down:
                self._check_shutdown_progress()
            await asyncio.sleep(self._config.CORE_TICK_RATE)
        print("[Kernel] Halted.")
