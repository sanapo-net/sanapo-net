# core/secretary.py
from typing import TYPE_CHECKING, Callable
if TYPE_CHECKING:
    from queue import Queue
    from main import Tools
    from core.config import Config

import time
import threading
from queue import Empty

from core import enums
from core.protocol import Frame
from core.logger import Logger

# TODO now i dont like self._thread = threading.Thread(target=self._worker_loop, daemon=True)
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

    # --- Initialisation ---

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

    def set_module(self, module: any) -> None:
        """
        Registers a module object with the secretary to call its methods directly. 
        Only for Kernel.
        """
        if self._module is not None:
            self._module = module
        else:
            self._log.err(f"[Secretary]: Detected second module set! Obj: {module}")

    def set_logger(self, logger: any) -> None:
        """
        Registers a logger object with the secretary to call its methods.
        Only for Kernel.
        """
        if self._log is None:
            if isinstance(logger, Logger):
                self._log = logger
            else:
                err = f"[{self.address.name}]: NonLoggerType get in Secretary.get_logger()"
                raise enums.SanapoError(err)
        else:
            self._log.err(f"[Secretary]: Detected second module set! Obj: {logger}")


    # --- Lifecycle management ---

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
        self._safe_send(
            msg_type=enums.MsgType.EVENT,
            evt_type=evt_type,
            payload=payload
        )

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

        self._safe_send(
            msg_type=enums.MsgType.COMMAND,
            recipient=recipient,
            cmd_type=cmd_type,
            cmd_id=cmd_id,
            payload=payload,
            deadline=d_done
        )

    def send_rpt(self,
                recipient: enums.Addr,
                cmd_id: str,
                rpt_type: enums.RptType,
                payload: dict[str, any] = {},
                time_ext_req: float = None
        ) -> None:
        """Sends a report (reply) to a commander."""
        self._safe_send(
                msg_type=enums.MsgType.REPORT,
                recipient=recipient,
                rpt_type=rpt_type,
                cmd_id=cmd_id,
                payload=payload,
                time_ext_req=time_ext_req  # _safe_send сам проигнорирует None, если во Frame он не обязателен
        )
        # Cleanup if the task is finished
        if rpt_type in [enums.RptType.DONE, enums.RptType.CANT_DO]:
            self._is_busy = False
            self._pending_in.pop(cmd_id, None)

    def modify_deadline(self, cmd_id: str, add_to_deadline: float) -> None:
        """
        Allows a commander to adjust the deadline of an active command.
        Only for Module as a Commander.
        """
        if cmd_id in self._pending_out:
            if add_to_deadline == self.FAIL:
                self._pending_out[cmd_id]["deadline_done"] = -1.0
            elif add_to_deadline == self.EVER:
                self._pending_out[cmd_id]["deadline_done"] = float('inf')
            else:
                self._pending_out[cmd_id]["deadline_done"] += add_to_deadline

    def _safe_send(self, **kwargs) -> None:
        """Internal helper to create and queue a frame with validation."""
        frame = None
        try:
            frame = Frame(sender=self.address, **kwargs)
        except enums.MessageInitError as e:
            m_type = kwargs.get('msg_type')
            sub_type = (kwargs.get('cmd_type') or kwargs.get('rpt_type') or 
                        kwargs.get('sys_type') or kwargs.get('evt_type'))
            m_name = m_type.name if m_type else "UNKNOWN"
            s_name = sub_type.name if hasattr(sub_type, 'name') else "UNKNOWN"
            self._log.crit(f"[Secretary]: Bus Protocol Violation [{m_name}:{s_name}]: {e}")
            return
        try:
            self._outbox.put(frame, block=False)
        except Exception as e:
            self._log.crit(f"[Secretary]: Outbox Error (Queue Full/Closed): {e}")

    def _send_sys(self, sys_type: enums.SysType, payload: dict[str, list]) -> None:
        """
        Sends system msg to kernel.
        Only for Secretary.
        """
        self._safe_send(
            msg_type=enums.MsgType.SYSTEM,
            sys_type=sys_type,
            payload=payload
        )

    def _log_push(self, evt_type: enums.EvtType, payload: dict[str, list]) -> None:
        """
        Safely send Frame to the Bus for MsgLogger.
        Only for Logger.
        """
        try:
            frame = Frame(
                msg_type=enums.MsgType.EVENT,
                sender=self.address,
                evt_type=evt_type,
                payload=payload
            )
            self._outbox.put(frame, block=False)
        except Exception as e:
            print(f"Critical: [{self.address.name}]: Logger transport failed: {e}")

    def _unregister(self) -> None:
        """
        Del this secretary from kernel registration system.
        Only for Kernel.
        """
        self._send_sys(enums.SysType.ADDR_DEREGISTER, [])


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
        start_ts = time.perf_counter()
        # Msg type map
        dispatch = {
            enums.MsgType.SYSTEM: self._process_system,
            enums.MsgType.EVENT:  self._process_event,
            enums.MsgType.COMMAND: self._process_command,
            enums.MsgType.REPORT: self._process_report,
        }
        handler = dispatch.get(frame.msg_type)
        if handler:
            handler(frame)
        else:
            self._log.err(f"Was got msg with Unknown type", frame, "MS")
        duration_ms = (time.perf_counter() - start_ts) * 1000
        self._log_task_duration(duration_ms, frame)

    def _process_system(self, frame: Frame) -> None:
        """Processing system signals."""
        if frame.sys_type == enums.SysType.SECR_STOP:
            self.stop()

    def _process_event(self, frame: Frame) -> None:
        """Processing event subscriptions."""
        handler = self._handlers_evt.get(frame.evt_type)
        if handler:
            handler(frame)
        else:
            self._log.err(f"[Secretary]: Was get evt, but module hasn't subcr", frame, "Se")

    def _process_command(self, frame: Frame) -> None:
        """
        Processing command subscriptions.
        Command logic: stop, busy and start checks.
        """
        # Stop
        if frame.cmd_type == enums.CmdType.MODULE_STOP:
            self._execute_module_stop(frame)
            return
        # Only for one-thread modules
        if not self.has_thread_pool and self._is_busy:
            self.send_rpt(frame.sender, frame.cmd_id,
                enums.RptType.CANT_DO,
                reason=enums.RptReason.MODULE_BUSY
            )
            return
        # Look for handler
        handler = self._handlers_cmd.get(frame.cmd_type)
        if handler and callable(handler):
            self._execute_command(handler, frame)
        else:
            self._log.err("[Secretary]: Command received, but no handler found", frame, "Sc")
            self.send_rpt(frame.sender, frame.cmd_id,
                enums.RptType.CANT_DO,
                reason=enums.RptReason.NOT_IMPLEMENTED)

    def _process_report(self, frame: Frame) -> None:
        """Handles incoming reports for commands sent by this module."""
        cmd_info = self._pending_out.get(frame.cmd_id)
        if not cmd_info:
            self._log.err(f"Get report with unknowed cmd_id", frame, "Sri")
            return

        if frame.rpt_type == enums.RptType.INTO_WORK:
            cmd_info["deadline_answ"] = float('inf') # Mark as 'Reaction Received'

        elif frame.rpt_type == enums.RptType.DONE:
            cmd_info["cb_done"](frame)
            self._pending_out.pop(frame.cmd_id)

        elif frame.rpt_type == enums.RptType.CANT_DO:
            cmd_info["cb_canttodo"](frame)
            self._pending_out.pop(frame.cmd_id)

        elif frame.rpt_type == enums.RptType.TIME_EXTENSION_REQUEST:
            if frame.time_ext_req:
                cmd_info["deadline_done"] += frame.time_ext_req
            cmd_info["cb_time_ext_req"](frame)

    def _execute_module_stop(self, frame: Frame) -> None:
        """Special logic for determining the stopping method."""
        # First look for in handlers, when try module.stop()
        handler = self._handlers_cmd.get(enums.CmdType.MODULE_STOP)
        if not handler and self._module is not None:
            handler = getattr(self._module, "stop", None)
        if callable(handler):
            handler(frame) 
        else:
            text = "[Secretary]: Called stop(), but module hasn't stop() handler"
            self._log.info(text, frame, "S")
            self.send_rpt(
                frame.sender,
                frame.cmd_id,
                enums.RptType.CANT_DO,
                reason=enums.RptReason.NOT_IMPLEMENTED
            )

    def _execute_command(self, handler: Callable, frame: Frame) -> None:
        """Internal life cycle of command execution."""
        self.send_rpt(frame.sender, frame.cmd_id, enums.RptType.INTO_WORK)
        self._is_busy = True 
        self._pending_in[frame.cmd_id] = {
            "deadline": frame.deadline,
            "sender": frame.sender
        }
        handler(frame)

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

    def _log_task_duration(self, duration_ms: float, frame: Frame) -> None:
        """Diagnostic tool to detect module blocking."""
        durs = [0.001, 0.01, 0,1, 0,25, 0,5, 1.0, 2.0, 4.0, 8.0]
        i = next((index for index, val in enumerate(durs) if duration_ms < val), len(durs))
        speed = f"speed_{i}"
        self._log.debug(f"Done {speed}: {duration_ms:.1f}ms", frame, "t")

