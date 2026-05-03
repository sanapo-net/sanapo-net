# sanapo/secretary.py
from __future__ import annotations
from time import perf_counter
from enum import Enum
from queue import Empty
from typing import TYPE_CHECKING

from sanapo.enums import MsgType, SysType, RptType, RptReason, MessageInitError
from sanapo.protocol import Frame
from sanapo.logger import Logger
from sanapo.base_unit import BaseUnit

if TYPE_CHECKING:
    from queue import Queue
    from sanapo.config import Config

EvtTypeClass = type[Enum]
CmdTypeClass = type[Enum]
Addr = Enum
CmdId = str
EvtType = Enum
CmdType = Enum

class Secretary:
    """
    Module's personal secretary. Runs in the module's thread.
    Handles deadlocks, automatically responds with INTO_WORK 
    and requests GIVE_ME_TIME when necessary.
    """
    # TODO do i need it
    # Semantic constants for deadline management.
    KEEP = 0.0           # No change to current deadline
    FAIL = -float('inf') # Task expires immediately
    EVER = float('inf')  # Task never expires

    def __init__(self, address: Addr, outbox: Queue, inbox: Queue, config: Config, 
                 logger: Logger, evt_enum: EvtTypeClass, cmd_enum: CmdTypeClass) -> None:
        
        self._addr: Addr = address
        self._unit: BaseUnit = None
        self._logger: Logger = logger
        self._inbox: Queue = inbox      # Read-only queue from Kernel
        self._outbox: Queue = outbox    # Write-only queue to Kernel
        self._config: Config = config

        self._evt_cls: EvtTypeClass = evt_enum
        self._cmd_cls: CmdTypeClass = cmd_enum
        self._handlers_cmd: dict[CmdType, callable] = {}
        self._handlers_evt: dict[EvtType, callable] = {}
        
        # Performance & Concurrency config.
        self._has_thread_pool: bool = False       # Set to True by module if it uses own threads
        self._module_is_busy: bool = False        # Internal flag for single-threaded modules
        self._log_task_duration_mode: bool = True # Toggle for health monitoring logs
        self._multi_reading : bool = False        # Flag of inbox multireading
        
        self._cmd_counter: int = 0
        # Commands sent by this Massenger (as Commander)
        # {cmd_id: {callbacks, deadlines, recipient, payload}}.
        self._cmd_out: dict[CmdId, dict[str, any]] = {}
        # Commands received by this Massenger (as Executor)
        # {cmd_id: {deadline, sender}}.
        self._cmd_in: dict[CmdId, dict[str, any]] = {}

        self._handlers_sys: dict[SysType, callable] = {
            SysType.U_START: self._unit.start,
            SysType.U_SLEEP: self._unit.sleep,
            SysType.U_WAKEUP: self._unit.wakeup,
            SysType.U_STOP: self._unit.stop,
            SysType.U_DESTROY: self._unit.destroy,
            SysType.U_STEP: self._unit.step,
            SysType.U_REBORN: self._unit.restart_module,
            SysType.U_MUTATE: self._unit.mutate,
        }

    def modify_deadline(self, cmd_id: str, add_to_deadline: float) -> bool:
        """
        Allows a commander to adjust the deadline of an active command.
        Returns True if it was changed successfully. Only for module as a Commander.
        """
        if cmd_id in self._cmd_out:
            self._cmd_out[cmd_id]["deadline_done"] = add_to_deadline
            return True
        else:
            self._logger.err(f"[Secr]: Modify deadline: cmd_id '{cmd_id}' not found")
            return False

    # --- Subscriptions ---

    def subscribe(self, cb: callable, cmd: Enum = None, evt: Enum = None) -> None:
        """Registers a callback for a specific command or event and notifies the Kernel."""
        payload = {}
        if cmd:
            self._handlers_cmd[cmd] = cb
            payload["cmd_list"] = [cmd]
        if evt:
            self._handlers_evt[evt] = cb
            payload["evt_list"] = [evt]
        if payload: self._send_sys(SysType.SUB, payload)

    def unsubscribe(self, cmd: Enum = None, evt: Enum = None) -> None:
        """Removes a registered callback and requests unsubscription from the Kernel."""
        payload = {}
        if cmd:
            self._handlers_cmd.pop(cmd, None)
            payload["cmd_list"] = [cmd]
        if evt:
            self._handlers_evt.pop(evt, None)
            payload["evt_list"] = [evt]
        if payload: self._send_sys(SysType.UNSUB, payload)

    def configure_subscriptions(self, events: dict[EvtTypeClass, callable] | None = None,
                                    commands: dict[CmdTypeClass, callable] | None = None) -> None:
        """
        Batch registers multiple handlers and synchronizes 
        current subscription state with the Kernel.
        """
        payload = {}
        if events:
            self._handlers_evt.update(events)
            payload["evt_list"] = list(events.keys())
        if commands:
            self._handlers_cmd.update(commands)
            payload["cmd_list"] = list(commands.keys())
        if payload: self._send_sys(SysType.SUB_SETUP, payload)

    # --- Outgoing messages ---

    def send_evt(self, evt_type: EvtType, payload: dict[str, any] = {}) -> bool:
        """Broadcast an event to the system bus."""
        return  self._safe_send(msg_type=MsgType.EVENT, evt_type=evt_type, payload=payload)

    def send_cmd(self,
                recipient: Addr,
                cmd_type: CmdType,
                cb: callable, 
                cb_done: callable | None = None,
                cb_canttodo: callable | None = None,
                cb_timeout_answ: callable | None = None,
                cb_timeout_done: callable | None = None,
                cb_time_ext_req: callable | None = None,
                deadline_answ_dur: float | None = None, # seconds
                deadline_done_dur: float | None = None, # seconds
                payload: dict[str, any] = {}
        ) -> bool:
        """
        Sends a command to a specific recipient and tracks it with multiple callbacks.
        If a specific callback is not provided, the default 'cb' is used.
        """
        self._cmd_counter += 1
        cmd_id = f"{self._addr}_{self._cmd_counter}"
        now = perf_counter()
        
        # Map specific callbacks to default if None
        cb_done = cb_done or cb
        cb_canttodo = cb_canttodo or cb
        cb_timeout_answ = cb_timeout_answ or cb
        cb_timeout_done = cb_timeout_done or cb
        cb_time_ext_req = cb_time_ext_req or cb

        # Calculate absolute deadlines
        d_answ = now + (deadline_answ_dur or self._config.DEFAULT_CMD_DEADLINE_ANSW)
        d_done = now + (deadline_done_dur or self._config.DEFAULT_CMD_DEADLINE_DONE)

        self._cmd_out[cmd_id] = {
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

        return self._safe_send(
            msg_type=MsgType.COMMAND,
            recipient=recipient,
            cmd_type=cmd_type,
            cmd_id=cmd_id,
            payload=payload,
            deadline=d_done
        )

    def send_rpt(self, recipient: Addr, cmd_id: str, rpt_type: RptType,
                payload: dict[str, any] = {}, time_ext_req: float = None) -> bool:
        """Sends a report (reply) to a commander."""
        # Cleanup if the task is finished
        if rpt_type in [RptType.DONE, RptType.CANT_DO]:
            self._module_is_busy = False
            self._cmd_in.pop(cmd_id, None)
            
        return self._safe_send(
                msg_type=MsgType.REPORT,
                recipient=recipient,
                rpt_type=rpt_type,
                cmd_id=cmd_id,
                payload=payload,
                time_ext_req=time_ext_req
        )
        
    def _send_sys(self, sys_type: SysType, payload: dict[str, any]) -> bool:
        """
        Sends system msg to kernel.
        Only for Secretary.
        """
        return self._safe_send(
            msg_type=MsgType.SYSTEM,
            sys_type=sys_type,
            payload=payload
        )

    def _safe_send(self, **kwargs) -> bool:
        """Internal helper to create and queue a frame with validation."""
        res = False
        frame = None
        try:
            frame = Frame(sender=self._addr, **kwargs)
            res = True
        except MessageInitError as e:
            m_type = kwargs.get('msg_type')
            sub_type = (kwargs.get('cmd_type') or kwargs.get('rpt_type') or 
                        kwargs.get('sys_type') or kwargs.get('evt_type'))
            m_name = m_type.name if m_type else "UNKNOWN"
            s_name = sub_type.name if hasattr(sub_type, 'name') else "UNKNOWN"
            self._logger.crt(f"[Secr]: Bus Protocol Violation [{m_name}:{s_name}]: {e}")
            return
        try:
            self._outbox.put(frame, block=False)
            res = True
        except Exception as e:
            self._logger.crt(f"[Secr]: Outbox Error (Queue Full/Closed): {e}")
        return res

    # TODO Do i need it? dont used (was for logger)
    def _log_push(self, evt_type: EvtType, payload: dict[str, list]) -> None:
        """
        Safely send Frame to the Bus for MsgLogger.
        Only for Logger.
        """
        try:
            frame = Frame(
                msg_type=MsgType.EVENT,
                sender=self._addr,
                evt_type=evt_type,
                payload=payload
            )
            self._outbox.put(frame, block=False)
        except Exception as e:
            print(f"Critical: [{self._addr.name}]: Logger transport failed: {e}")

    # --- Internal logic ---

    def _handle_frame(self, frame: Frame) -> bool:
        """
        Processes a single incoming frame,
        Returns True if callback was called.
        """
        start_ts = perf_counter()
        # Msg type map.
        dispatch = {
            MsgType.SYSTEM: self._process_system,
            MsgType.EVENT:  self._process_event,
            MsgType.COMMAND: self._process_command,
            MsgType.REPORT: self._process_report,
        }
        handler = dispatch.get(frame.msg_type)
        if handler:
            res = handler(frame)
        else:
            self._logger.err(f"[Secr]: Was got msg with Unknown type", frame, "MS")
            return False
        self._log_task_duration(perf_counter() - start_ts, frame)
        return res

    def _process_system(self, frame: Frame) -> bool:
        """
        Processes system frames by dispatching to registered callbacks.
        Executes validated handlers with unpacked arguments and logs errors.
        """
        callback = self._handlers_sys.get(frame.sys_type, None)
        if not callback:
            self._logger.err(f"[Secr]: Unsupported", frame, "M")
            return False
        if not callable(callback):
            self._logger.crt(f"[Secr]: Not callable! Data:{callback}", frame, "M")
            return False
        args = frame.payload.get("args", tuple())
        self._logger.dbg(f"[Secr]: Call {callback.__name__} with {args}")
        try:
            res = callback(*args)
            self._logger.dbg(f"[Secr]: Call callback:{callback} returned:{res}")
            return True
        except Exception as e:
            self._logger.err(f"[Secr]: SysCallback error: {e}")
            return False

    def _process_event(self, frame: Frame) -> bool:
        """
        Processing event subscriptions,
        rerurn True if was called callback.
        """
        handler = self._handlers_evt.get(frame.evt_type)
        if handler:
            handler(frame)
            return True
        else:
            self._logger.err(f"[Secr]: Was get evt, but module hasn't subcr", frame, "Se")
            return False

    def _process_command(self, frame: Frame) -> bool:
        """
        Processing command subscriptions.
        Command logic: stop, busy and start checks.
        Returns True if callback was called.
        """
        # Only for one-thread modules
        if not self._has_thread_pool and self._module_is_busy:
            self.send_rpt(frame.sender, frame.cmd_id,
                RptType.CANT_DO,
                reason=RptReason.MODULE_BUSY)
            return False
        # Look for handler
        handler = self._handlers_cmd.get(frame.cmd_type)
        if handler and callable(handler):
            return self._execute_command(handler, frame)
        else:
            self._logger.err("[Secr]: Command received, but no handler found", frame, "Sc")
            self.send_rpt(frame.sender, frame.cmd_id,
                RptType.CANT_DO,
                reason=RptReason.NOT_IMPLEMENTED)
            return False

    def _process_report(self, frame: Frame) -> bool:
        """
        Handles incoming reports for commands sent by this module.
        Returns True if callback was called.
        """
        res = False
        cmd_info = self._cmd_out.get(frame.cmd_id)
        if not cmd_info:
            self._logger.err(f"Get report with unknowed cmd_id", frame, "Sri")
            return res

        if frame.rpt_type == RptType.INTO_WORK:
            cmd_info["deadline_answ"] = float('inf') # Mark as 'Reaction Received'
            res = True

        elif frame.rpt_type == RptType.DONE:
            cmd_info["cb_done"](frame)
            self._cmd_out.pop(frame.cmd_id)
            res = True

        elif frame.rpt_type == RptType.CANT_DO:
            cmd_info["cb_canttodo"](frame)
            self._cmd_out.pop(frame.cmd_id)
            res = True

        elif frame.rpt_type == RptType.TIME_EXTENSION_REQUEST:
            if frame.time_ext_req:
                cmd_info["deadline_done"] += frame.time_ext_req
            res = True
            cmd_info["cb_time_ext_req"](frame)
            res = True
        return res

    def _execute_command(self, handler: callable, frame: Frame) -> bool:
        """
        Internal life cycle of command execution.
        Returns True if callback was called
        """
        self.send_rpt(frame.sender, frame.cmd_id, RptType.INTO_WORK)
        self._module_is_busy = True 
        self._cmd_in[frame.cmd_id] = {"deadline": frame.deadline, "sender": frame.sender}
        handler(frame)
        self._module_is_busy = False
        return True

    def _check_deadlines(self) -> bool:
        """Validates all time constraints for outgoing and incoming tasks."""
        now = perf_counter()
        was_work = False
        # Check outgoing commands (waiting for Executor to act).
        for cmd_id, info in list(self._cmd_out.items()):
            was_work = True
            if now > info["deadline_answ"]:
                info["cb_timeout_answ"]({"cmd_id": cmd_id, "reason": "Reaction Timeout"})
                self._cmd_out.pop(cmd_id)
            elif now > info["deadline_done"]:
                info["cb_timeout_done"]({"cmd_id": cmd_id, "reason": "Execution Timeout"})
                self._cmd_out.pop(cmd_id)

        # Automatic deadline extension (when we are the Executor).
        # If remaining time is below threshold - automatically request more time.
        threshold = self._config.DEADLINE_EXTENSION_THRESHOLD 
        for cmd_id, info in list(self._cmd_in.items()):
            was_work = True
            if info["deadline"] - now < threshold:
                extension = self._config.DEFAULT_TIME_EXTENSION
                self.send_rpt(
                    info["sender"],
                    cmd_id,
                    RptType.TIME_EXTENSION_REQUEST,
                    time_ext_req=extension
                )
                info["deadline"] += extension
        return was_work

    def _log_task_duration(self, duration: float, frame: Frame) -> None:
        """Diagnostic tool to detect module blocking."""
        duration_ms = duration * 1000
        durs = [0.001, 0.01, 0,1, 0,25, 0,5, 1.0, 2.0, 4.0, 8.0]
        i = next((index for index, val in enumerate(durs) if duration_ms < val), len(durs))
        speed = f"speed_{i}"
        self._logger.dbg(f"[Secr]: Done {speed}: {duration_ms:.1f}ms", frame, "t")
    
    def _set_unit(self, unit: BaseUnit) -> bool:
        """
        Registers a module object with the secretary to call its methods directly. 
        Only for Kernel.
        """
        if isinstance(unit, BaseUnit):
            self._logger.err(f"[Secr]: set_unit: get not BaseUnit: {unit}")
            return False
        if self._unit is not None:
            self._logger.err(f"[Secr]: set_unit: Detected second set! Obj: {unit}")
            return False
        self._unit = unit
        return True

    def _step(self) -> bool:
        """
        Executes one cycle of secretary work.
        Returns True if there was activity
        (was income messages or chekings deadline).
        """
        was_active = False
        
        # Read inbox.
        try:
            # Read firts msg
            self._handle_frame(self._inbox.get_nowait())
            was_active = True
            
            if self._multi_reading:
                readed = 1
                while True:
                    try:
                        self._handle_frame(self._inbox.get_nowait())
                        readed += 1
                        if readed >= self._config.UNIT_BUS_READ_LIMIT:
                            self._logger.wrn(f"[Secr]: Bus read limit reached ({readed})")
                            break
                    except Empty:
                        break
        except Empty:
            pass

        # Check deadlines
        if self._cmd_out or self._cmd_in:
            if self._check_deadlines():
                was_active = True
        return was_active
