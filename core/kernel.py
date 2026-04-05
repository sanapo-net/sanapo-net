# core/kernel.py
import asyncio
from queue import Queue, Empty
import time

from core.enums import Addr, MsgType, CmdType, EvtType, RptType, SysType
from core.enums import AddressBusyError, UnknownAddressError
from core.protocol import Frame
from core.secretary import Secretary

class Kernel:
    def __init__(self, _tools):
        self._tools = _tools
        self._bus = Queue() 
        self._registry: dict[Addr, Queue] = {}
        self._subscribers_evt: dict[EvtType, set[Addr]] = {}
        self._subscribers_cmd: dict[CmdType, set[Addr]] = {}
        #self._subscribers_rpt: dict[RptType, set[Addr]] = {}
        self._is_running = True
        self._tick_counter = 0
        self._ticks_lookup = (
            (240, EvtType.TICK_120),
            (48,  EvtType.TICK_24),
            (16,  EvtType.TICK_8),
            (8,   EvtType.TICK_4),
            (4,   EvtType.TICK_2),
            (2,   EvtType.TICK_1),
        )
        

    def _check_and_run_ticker(self):
        now = time.time()
        if now >= self._next_tick_time:
            self._ticker()
            self._next_tick_time = now + 0.5 


    def _ticker(self):
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


    def get_secr(self, addr: Addr) -> Secretary:
        if not isinstance(addr, Addr):
            raise UnknownAddressError(f"Address '{addr}' is not defined in Addr enum.")
        if addr in self._registry:
            raise AddressBusyError(f"Address '{addr}' is already registered by another module.")
        config = self._tools.config
        outbox = self._bus
        inbox = Queue()
        self._registry[addr] = inbox
        return Secretary(addr, outbox, inbox, config)
    

    def _addr_deregister(self, addr: Addr):
        """Final cleanup: wipes the address from all registries and subscriptions."""
        # Delete addr from subscribers
        for sub_dict in [self._subscribers_evt, self._subscribers_cmd]:
            for listeners in sub_dict.values():
                listeners.discard(addr)
        # Delete Queue of module by addr
        self._registry.pop(addr, None)
        # Send event
        self._send_evt(EvtType.EVT_ADDR_DEREGISTER, {"addr":addr})


    def _system_msg_handler(self, frame):
        """Universal handler for all subscriptions and deregistrations."""
        if sys_type == SysType.SYS_ADDR_DEREGISTER:
            return self._addr_deregister(frame.sender)
        
        addr = frame.sender
        sys_type = frame.sys_type
        if isinstance(frame.payload, list):
            msg_sub_types = frame.payload
        else:
            text = f"SysType.{sys_type}: payload is wrong. payload: {frame.payload}"
            self._send_evt(EvtType.ERR_LOGIC, {"text":text})

        # Mapping system types to internal subscriber dictionaries
        target_map = {
            SysType.SUB_EVT: (self._subscribers_evt, "add"),
            SysType.UNSUB_EVT: (self._subscribers_evt, "discard"),
            SysType.SUB_EVT_SETUP: (self._subscribers_evt, "setup"),
            
            SysType.SUB_CMD: (self._subscribers_cmd, "add"),
            SysType.UNSUB_CMD: (self._subscribers_cmd, "discard"),
            SysType.SUB_CMD_SETUP: (self._subscribers_cmd, "setup"),
        }

        if sys_type in target_map:
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
    

    def route_messages(self):
        """
        Main mail sorter (Main Thread).
        Processes the incoming _bus and distributes messages to module inboxes.
        """
        now = time.perf_counter()
        q_size = self._bus.qsize()

        # Overcrowd checking. Once every 1 second send event if the _bus is overcrowded.
        if q_size > self.config.BUS_READ_LIMIT:
            if now - self._last_overcrowded_alert > 1.0:
                self._send_evt(EvtType.BUS_IS_OVERCROWDED, {"text":f"Current _bus size: {q_size}"})
                self._last_overcrowded_alert = now

        # Message parsing cycle
        processed_count = 0
        try:
            while not self._bus.empty() and processed_count < self.config.BUS_READ_LIMIT:
                frame = self._bus.get_nowait()
                processed_count += 1

                # SYSTEM message
                if frame.msg_type == MsgType.SYSTEM:
                    if frame.sys_type == SysType.APP_STOP:
                        self._shutdown_initialization()
                    else:
                        self._system_msg_handler(frame)
                    break

                # COMMAND message
                elif frame.msg_type == MsgType.COMMAND:
                    dest = frame.recipient
                    if dest in self._registry:
                        # Find address-set in the dict of cmd subscribers
                        allowed_handlers = self._subscribers_cmd.get(frame.cmd_type, set())
                        if dest not in allowed_handlers:
                            # Executor exists, but it not subscribed for this CmdType
                            # NO_SUBSCRIBED_EXECUTOR
                            self._send_rpt(frame, RptType.NO_SUBSCRIBED_EXECUTOR)
                            break
                        # Executor exists and is subscribed - > send cmd
                        self._registry[dest].put_nowait(frame)
                    else:
                        # NO_REGISTRED_EXECUTOR
                        self._send_rpt(frame, RptType.NO_REGISTRED_EXECUTOR)
                        break

                # REPORTS message
                elif frame.msg_type == MsgType.REPORT:
                    dest = frame.recipient
                    if dest in self._registry:
                        self._registry[dest].put_nowait(frame)

                # EVENT message
                elif frame.msg_type == MsgType.EVENT:
                    # Find subscribers-set in the dict of event subscribers
                    subscribers = self._subscribers_evt.get(frame.evt_type, set())
                    for addr in subscribers:
                        # Dont send event to autor
                        if addr != frame.sender and addr in self._registry:
                            self._registry[addr].put_nowait(frame)
        except Empty:
            pass
        except Exception as e:
            print(f"[ERROR] Routing failed: {e}")


    def _send_evt(self, type: EvtType, payload: dict):
        frame=Frame(MsgType.EVENT, Addr.KERNEL, evt_type=type, payload=payload)
        self._bus.put_nowait(frame)


    def _send_rpt(self, cmd:Frame, type:RptType, payload:dict):
        commander = cmd.sender
        cmd_id = cmd.cmd_id
        text = f"From: {cmd.sender} To: {commander} Type: {cmd.msg_type} "
        text += f"SubType: {cmd.cmd_type or cmd.rpt_type or 'None'} cmd_id: {cmd_id}"
        p = {"text":text}
        rpt = Frame(MsgType.REPORT, Addr.KERNEL, rpt_type=type, cmd_id=cmd_id, payload=p)
        self._bus.put_nowait(rpt)


    def _shutdown_initialization(self):
        # TODO correctly shutdown
        self.stop()


    def stop(self):
        print("[Kernel] Shutdown initiated...")
        self._is_running = False


    async def launch(self):
        """core starter"""
        print("[Kernel] Running...")
        while self._is_running:
            self.route_messages()
            self._check_and_run_ticker()
            await asyncio.sleep(self.config.CORE_TICK_RATE)
        print("[Kernel] Halted.")
