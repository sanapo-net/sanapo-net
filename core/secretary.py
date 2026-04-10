# core/secretary.py
from typing import TYPE_CHECKING, Callable
if TYPE_CHECKING:
    from queue import Queue
    from main import Tools
    from core.config import Config
    from core.logger import Logger

import time
import threading
from queue import Empty

from core import enums
from core.protocol import Frame

# TODO add MessageInitError cheking
# TODO add send-methods for looger
class Secretary:
    """
    Module's personal secretary. Runs in the module's thread.
    Handles deadlocks, automatically responds with INTO_WORK 
    and requests GIVE_ME_TIME when necessary.
    """
    
    # Semantic constants for deadline management
    KEEP = 0.0          # No change to current deadline
    FAIL = -float('inf')# Task expires immediately
    EVER = float('inf') # Task never expires

    def __init__(self,
            address: enums.Addr,
            outbox: Queue,
            inbox: Queue,
            tools: Tools,
            logger: Logger
    ) -> None:
        
        self.address: enums.Addr = address
        self._module: any = None
        self._log: Logger = logger
        self._inbox: Queue = inbox      # Read-only queue from Kernel
        self._outbox: Queue = outbox    # Write-only queue to Kernel
        self._config: Config = tools.config

        self.has_thread_pool: bool = False  # Set to True by module if it uses own thread

        self._cmd_counter: int = 0
        self._handlers_cmd: dict[enums.CmdType, Callable] = {}
        self._handlers_evt: dict[enums.EvtType, Callable] = {}
        # Performance & Concurrency config
        self._tick_rate: float = self._config.get_secretary_tick(address.name)
        self._is_busy: bool = False         # Internal flag for single-threaded modules
        self._console_log_enabled: bool = True   # Toggle for health monitoring logs
        
        # Commands sent by this Massenger (as Commander)
        # {cmd_id: {callbacks, deadlines, recipient, payload}}
        self._pending_out: dict[str, dict[str, any]] = {}
        # Commands received by this Massenger (as Executor)
        self._pending_in: dict[str, dict[str, any]] = {}  # {cmd_id: {deadline, sender}}

        self._is_running: bool = False
        self._thread: threading.Thread | None = None

        self._send_sys(enums.SysType.SUB_CMD, {"list":[enums.CmdType.MODULE_STOP]})


    # --- Lifecycle management ---
    def set_module(self, module: any) -> None:
        if self._module is not None:
            self._module = module
        else:
            self._log.err(f"[Secretary]: Detected second module set! Obj: {module}")

    def set_logger(self, logger: any) -> None:
        """Registers a logger object with the secretary to call its methods."""
        if self._log is None:
            if isinstance(logger, Logger):
                self._log = logger
            else:
                err = f"[{self.address.name}]: NonLoggerType get in Secretary.get_logger()"
                raise enums.SanapoError(err)
        else:
            self._log.err(f"[Secretary]: Detected second module set! Obj: {logger}")


    def start(self) -> None:
        """Starts the background worker for message processing and deadline checks."""
        if not self._is_running:
            self._is_running = True
            self._thread = threading.Thread(target=self._worker_loop, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """Stops the secretary's background thread."""
        self._is_running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._log.info(f"[Secretary]: {self.address.name} halted.")

    def process_once(self) -> None:
        """Single pass through the inbox and deadline checks (for sync or async calls)."""
        self._read_inbox()
        self._check_deadlines()

    def _worker_loop(self) -> None:
        """
        Internal background loop with time compensation.
        Ensures stable tick rate regardless of logic execution time.
        """
        while self._is_running:
            # Fixed Timestep Loop
            start_time = time.perf_counter()
            self.process_once()
            work_duration = time.perf_counter() - start_time
            sleep_time = self._tick_rate - work_duration
            if sleep_time > 0:
                time.sleep(sleep_time)
            else:    
                time.sleep(0) # Yield for other threads


    # --- Subscriptions ---

    def subscribe(self,
            cb: Callable,
            cmd_type: enums.CmdType = None,
            evt_type: enums.EvtType = None
        ) -> None:
        """Register a callback for a specific command or event type."""
        if cmd_type:
            self._handlers_cmd[cmd_type] = cb
            self._send_sys(enums.SysType.SUB_CMD, [cmd_type])
        if evt_type:
            self._handlers_evt[evt_type] = cb
            self._send_sys(enums.SysType.SUB_EVT, [evt_type])

    def unsubscribe(self, cmd_type: enums.CmdType = None, evt_type: enums.EvtType = None) -> None:
        """Remove a previously registered callback."""
        if cmd_type:
            self._handlers_cmd.pop(cmd_type, None)
            self._send_sys(enums.SysType.UNSUB_CMD, [cmd_type])
        if evt_type:
            self._handlers_evt.pop(evt_type, None)
            self._send_sys(enums.SysType.UNSUB_EVT, [evt_type])

    def configure_subscriptions(self,
            events: dict[enums.EvtType, Callable] = None, 
            commands: dict[enums.CmdType, Callable] = None
        ) -> None:
        """Batch register multiple handlers using dictionaries."""
        if events:
            self._handlers_evt.update(events)
            self._send_sys(enums.SysType.SUB_EVT_SETUP, list(events.keys()))
        if commands:
            self._handlers_cmd.update(commands)
            self._send_sys(enums.SysType.SUB_CMD_SETUP, list(commands.keys()))


    # --- Outgoing messages ---

    def send_evt(self, evt_type: enums.EvtType, payload: dict[str, any] = {}) -> None:
        """Broadcast an event to the system bus."""
        frame = Frame(
            msg_type=enums.MsgType.EVENT,
            sender=self.address,
            evt_type=evt_type,
            payload=payload
        )
        self._outbox.put(frame)

    def send_cmd(self,
            recipient: enums.Addr,
            cmd_type: enums.CmdType,
            cb: Callable, 
            cb_done: Callable | None = None,
            cb_canttodo: Callable | None = None,
            cb_timeout_answ: Callable | None = None,
            cb_timeout_done: Callable | None = None,
            cb_time_ext_req: Callable | None = None,
            deadline_answ_dur: float | None = None, # seconds
            deadline_done_dur: float | None = None, # seconds
            payload: dict[str, any] = {}
        ) -> None:
        """
        Sends a command to a specific recipient and tracks it with multiple callbacks.
        If a specific callback is not provided, the default 'cb' is used.
        """
        self._cmd_counter += 1
        cmd_id = f"{self.address}_{self._cmd_counter}"
        now = time.perf_counter()
        
        # Map specific callbacks to default if None
        cb_done = cb_done or cb
        cb_canttodo = cb_canttodo or cb
        cb_timeout_answ = cb_timeout_answ or cb
        cb_timeout_done = cb_timeout_done or cb
        cb_time_ext_req = cb_time_ext_req or cb

        # Calculate absolute deadlines
        d_answ = now + (deadline_answ_dur or self._config.DEFAULT_CMD_DEADLINE_ANSW)
        d_done = now + (deadline_done_dur or self._config.DEFAULT_CMD_DEADLINE_DONE)

        self._pending_out[cmd_id] = {
            "cb_done": cb_done,
            "cb_canttodo": cb_canttodo, 
            "cb_timeout_answ": cb_timeout_answ,
            "cb_timeout_done": cb_timeout_done, 
            "cb_time_ext_req": cb_time_ext_req,
            "deadline_answ": d_answ,
            "deadline_done": d_done, 
            "recipient": recipient,
            "payload": payload
        }

        frame = Frame(
            msg_type=enums.MsgType.COMMAND,
            sender=self.address,
            recipient=recipient,
            cmd_type=cmd_type,
            cmd_id=cmd_id,
            payload=payload,
            deadline=d_done
        )
        self._outbox.put(frame)

    def send_rpt(self,
            recipient: enums.Addr,
            cmd_id: str,
            rpt_type: enums.RptType,
            payload: dict[str, any] = {},
            time_ext_req: float = None
        ) -> None:
        """Sends a report (reply) to a commander."""
        
        # Preparing base parameters
        kwargs = {
            "msg_type": enums.MsgType.REPORT,
            "sender": self.address,
            "recipient": recipient,
            "rpt_type": rpt_type,
            "cmd_id": cmd_id,
            "payload": payload
        }

        # Specific
        if rpt_type == enums.RptType.TIME_EXTENSION_REQUEST:
            kwargs["time_ext_req"] = time_ext_req

        frame = Frame(**kwargs)
        self._outbox.put(frame)

        # Cleanup if the task is finished
        if rpt_type in [enums.RptType.DONE, enums.RptType.CANT_DO]:
            self._is_busy = False
            self._pending_in.pop(cmd_id, None)

    def _send_sys(self, sys_type: enums.SysType, payload: dict[str, list]) -> None:
        """Sends system msg to kernel."""
        frame = Frame(
            msg_type=enums.MsgType.SYSTEM,
            sender=self.address,
            sys_type=sys_type,
            payload=payload
        )
        self._outbox.put(frame)
    
    def send_err_app(self, text: str) -> None:
        """Send & Print APPLogicErrorText as Module"""
        print(f"[{self.address.name}]: APPLogicError: {text}")
        self.send_evt(enums.EvtType.ERR_LOGIC, {"text":text})

    def _send_err_app(self, text: str) -> None:
        """Send & Print APPLogicErrorText as Secretary"""
        print(f"[SECRETARY]: APPLogicError: {text}")
        self.send_evt(enums.EvtType.ERR_LOGIC, {"text":text})
    
    def send_err(self, text: str) -> None:
        """Send & Print UserErrorText"""
        print(f"[{self.address.name}]: Error: {text}")
        self.send_evt(enums.EvtType.ERR, {"text":text})

    def send_log(self, text: str) -> None:
        """Send & Print LogText"""
        print(f"[{self.address.name}]: Log: {text}")
        self.send_evt(enums.EvtType.LOG, {"text":text})

    def send_msg(self, text: str) -> None:
        """Send & Print UserMsgText"""
        print(f"[{self.address.name}]: Msg: {text}")
        self.send_evt(enums.EvtType.MSG, {"text":text})

    def send_wrn(self, text: str) -> None:
        """Send & Print UserWarningText"""
        print(f"[{self.address.name}]: Warning: {text}")
        self.send_evt(enums.EvtType.WRN, {"text":text})

    def unregister(self) -> None:
        """del this secr from kernel registration system"""
        self._send_sys(enums.SysType.ADDR_DEREGISTER, [])

    def modify_deadline(self, cmd_id: str, add_to_deadline: float) -> None:
        """Allows a commander to adjust the deadline of an active command."""
        if cmd_id in self._pending_out:
            if add_to_deadline == self.FAIL:
                self._pending_out[cmd_id]["deadline_done"] = -1.0
            elif add_to_deadline == self.EVER:
                self._pending_out[cmd_id]["deadline_done"] = float('inf')
            else:
                self._pending_out[cmd_id]["deadline_done"] += add_to_deadline


    # --- Internal logic ---

    def _read_inbox(self) -> None:
        """Fetches messages from the personal module inbox."""
        try:
            while not self._inbox.empty():
                frame = self._inbox.get_nowait()
                self._handle_frame(frame)
        except Empty:
            pass

    def _handle_frame(self, frame: Frame) -> None:
        """Processes a single incoming frame with life-cycle management."""
        # SYSTEM
        if frame.msg_type == enums.MsgType.SYSTEM:
            # SECR_STOP
            if frame.sys_type == enums.SysType.SECR_STOP:
                self.stop()
            return
        # EVENT
        elif frame.msg_type == enums.MsgType.EVENT:
            handler = self._handlers_evt.get(frame.evt_type)
            if handler:
                handler(frame)
            return
        # REPORT
        elif frame.msg_type == enums.MsgType.REPORT:
            self._handle_report(frame)
            return
        # COMMAND
        elif frame.msg_type == enums.MsgType.COMMAND:
            # MODULE_STOP
            if frame.cmd_type == enums.CmdType.MODULE_STOP:
                handler = self._handlers_cmd.get(enums.CmdType.MODULE_STOP)
                if not handler and self._module is not None:
                    handler = getattr(self._module, "stop", None)

                if callable(handler):
                    handler(frame)
                else:
                    self._log.info("[Secretary]: called stop(), but module hasn't stop() handler")
                    self.send_rpt(
                        frame.sender, frame.cmd_id, 
                        enums.RptType.CANT_DO, 
                        reason=enums.RptReason.NOT_IMPLEMENTED
                    )
                return
            
            # Busy managment: CANT_DO: MODULE_BUSY
            # _is_busy: have a command and has not sent a report CANT_DO/DONE)
            if not self.has_thread_pool and self._is_busy:
                self.send_rpt(
                    recipient=frame.sender,
                    cmd_id=frame.cmd_id,
                    rpt_type=enums.RptType.CANT_DO,
                    reason=enums.RptReason.MODULE_BUSY,
                )
                return
            
            # Module is free:            
            handler = self._handlers_cmd.get(frame.cmd_type)
            if handler and callable(handler): 
                # Handler exist
                # Automatic handshake INTO_WORK
                self.send_rpt(frame.sender, frame.cmd_id, enums.RptType.INTO_WORK)
                self._is_busy = True 
                # Monitor this command for automatic TIME_EXTENSION_REQUEST requests
                self._pending_in[frame.cmd_id] = {
                    "deadline": frame.deadline,
                    "sender": frame.sender
                }
                handler(frame)
            else:
                # Handler doesn't exist
                # This shouldn't happen because the kernel shouldn't route
                #     a command here if it isn't subscribed to.
                self._log.err(f"[Secretary]: Was get a command, but hasn't handler", frame, "Sc")
                self.send_rpt(
                    frame.sender, frame.cmd_id, 
                    enums.RptType.CANT_DO, 
                    reason=enums.RptReason.NOT_IMPLEMENTED
                )


        start_ts = time.perf_counter()

        # For console logging: checking durations and alarm if the work was long
        duration_ms = (time.perf_counter() - start_ts)
        self._log_latency(duration_ms, frame)

    def _handle_report(self, frame: Frame) -> None:
        """Handles incoming reports for commands sent by this module."""
        info = self._pending_out.get(frame.cmd_id)
        if not info: return

        if frame.rpt_type == enums.RptType.INTO_WORK:
            info["deadline_answ"] = float('inf') # Mark as 'Reaction Received'

        elif frame.rpt_type == enums.RptType.DONE:
            info["cb_done"](frame)
            self._pending_out.pop(frame.cmd_id)

        elif frame.rpt_type == enums.RptType.CANT_DO:
            info["cb_canttodo"](frame)
            self._pending_out.pop(frame.cmd_id)

        elif frame.rpt_type == enums.RptType.TIME_EXTENSION_REQUEST:
            if frame.time_ext_req:
                info["deadline_done"] += frame.time_ext_req
            info["cb_time_ext_req"](frame)

    def _check_deadlines(self) -> None:
        """Validates all time constraints for outgoing and incoming tasks."""
        now = time.perf_counter()

        # Check outgoing commands (waiting for Executor to act)
        for cmd_id, info in list(self._pending_out.items()):
            if now > info["deadline_answ"]:
                info["cb_timeout_answ"]({"cmd_id": cmd_id, "reason": "Reaction Timeout"})
                self._pending_out.pop(cmd_id)
            elif now > info["deadline_done"]:
                info["cb_timeout_done"]({"cmd_id": cmd_id, "reason": "Execution Timeout"})
                self._pending_out.pop(cmd_id)

        # Automatic deadline extension (when we are the Executor)
        # If remaining time is below threshold - automatically request more time
        threshold = self._config.DEADLINE_EXTENSION_THRESHOLD 
        for cmd_id, info in list(self._pending_in.items()):
            if info["deadline"] - now < threshold:
                extension = self._config.DEFAULT_TIME_EXTENSION
                self.send_rpt(
                    info["sender"],
                    cmd_id,
                    enums.RptType.TIME_EXTENSION_REQUEST,
                    time_ext_req=extension
                )
                info["deadline"] += extension


    # --- Console logging ---

    def _log_latency(self, duration_ms: float, frame: Frame) -> None:
        """Internal diagnostic tool to detect module blocking."""
        if not self._console_log_enabled:
            return
            
        thresholds = [0.1, 0.25, 0.5, 1, 2, 4, 8]
        triggered = [t for t in thresholds if duration_ms >= t]
        
        if triggered:
            max_t = max(triggered)
            level = "CRITICAL" if max_t >= 1000 else "WARNING"
            
            # Contextual info based on message type
            ctx = f"Type: {frame.msg_type.name}"
            if frame.evt_type: ctx += f", Evt: {frame.evt_type}"
            if frame.cmd_type: ctx += f", Cmd: {frame.cmd_type}"
            if frame.cmd_id:   ctx += f", ID: {frame.cmd_id}"
            
            print(f"[{level} > {max_t}ms] Module {self.address.name} BLOCKED Secretary! "
                  f"Duration: {duration_ms:.1f}ms. Context: {ctx}. "
                  f"Sender: {frame.sender.name}. Payload: {frame.payload}")
