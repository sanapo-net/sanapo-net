# sanapo/secretary.py
from __future__ import annotations
from time import perf_counter
from queue import Empty
from typing import TYPE_CHECKING

from sanapo.enums import MsgType, SysType, RptType, RptReason, MessageInitError
from sanapo.protocol import Frame
from sanapo.base_unit import BaseUnit
from sanapo.addr import Addr

if TYPE_CHECKING:
    from enum import Enum
    from typing import Type
    from queue import Queue
    from sanapo.config import Config
    from sanapo.logger import Logger
    EvtType = Enum
    CmdType = Enum
    EvtTypeClass = Type[Enum]
    CmdTypeClass = Type[Enum]
    CmdId = str

class Secretary:
    """
    Module's personal secretary. Runs in the module's thread.
    Handles deadlocks, automatically responds with INTO_WORK 
    and requests GIVE_ME_TIME when necessary.
    """
    # Semantic constants for deadline management.
    KEEP = 0.0           # No change to current deadline
    FAIL = -float('inf') # Task expires immediately
    EVER = float('inf')  # Task never expires

    def __init__(self,
                address: Addr,
                outbox: Queue,
                inbox: Queue,
                config: Config,
                logger: Logger,
                evt_class: EvtTypeClass,
                cmd_class: CmdTypeClass,
                resurrect_func: callable
            ) -> None:
        
        self._addr: Addr = address
        self._unit: BaseUnit = None
        self._logger: Logger = logger
        self._inbox: Queue = inbox      # Read-only queue from Kernel
        self._outbox: Queue = outbox    # Write-only queue to Kernel
        self._config: Config = config

        self._evt_cls: EvtTypeClass = evt_class
        self._cmd_cls: CmdTypeClass = cmd_class
        self._handlers_cmd: dict[CmdType, callable] = {}
        self._handlers_evt: dict[EvtType, callable] = {}
        self._cmd_expired: list[str] = []
        
        self._resurrect: callable = resurrect_func
        
        # Performance & Concurrency config.
        self._has_thread_pool: bool = False       # set to True by module if it uses own threads
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

    def auto_subscribe(self) -> None:
        self._handlers_sys: dict[SysType, callable] = {
            SysType.U_START: self._unit.start,
            SysType.U_SLEEP: self._unit.sleep,
            SysType.U_WAKEUP: self._unit.wakeup,
            SysType.U_STOP: self._unit.stop,
            SysType.U_DESTROY: self._unit.destroy,
            SysType.U_STEP: self._unit.step,
            SysType.U_REBORN: self._unit.restart_module,
            SysType.U_MUTATE: self._unit.mutate,
            # TODO in v2: Should the secretary call non-network units?
            SysType.NET_CONNECTED: self._unit.on_net_connected,
            SysType.NET_DISCONNECTED: self._unit.on_net_disconnected,
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
            self._logger.err("SECR: Modify deadline: cmd_id '{cmd_id}' not found", cmd_id=cmd_id)
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
        return  self._safe_send(msg_type=MsgType.EVT, evt_type=evt_type, payload=payload)

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
        cmd_id = f"{self._addr.to_net(self._config.SYSTEM_NAME)}@{self._cmd_counter}"
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
            msg_type=MsgType.CMD,
            recipient=recipient,
            cmd_type=cmd_type,
            cmd_id=cmd_id,
            payload=payload,
            deadline=d_done
        )

    def send_rpt(self, recipient: Addr, cmd_id: str, rpt_type: RptType,
                payload: dict[str, any] = {}, time_ext_req: float = None,
                reason: RptReason | None = None) -> bool:
        """Sends a transaction report back to the commander container loop."""
        if rpt_type in [RptType.DONE, RptType.CANT_DO]:
            self._module_is_busy = False
            self._cmd_in.pop(cmd_id, None)
        return self._safe_send(
                msg_type=MsgType.RPT,
                recipient=recipient,
                rpt_type=rpt_type,
                cmd_id=cmd_id,
                payload=payload,
                time_ext_req=time_ext_req,
                reason=reason # Forward the concrete validation reason token
        )

        
    def _send_sys(self, sys_type: SysType, payload: dict[str, any]) -> bool:
        """
        Sends system msg to kernel.
        Only for Secretary.
        """
        return self._safe_send(
            msg_type=MsgType.SYS,
            recipient=self._config.ADDR_KERNEL,
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
            m_name = getattr(m_type, 'name', None) or m_type or "UNKNOWN"
            s_name = getattr(sub_type, 'name', None) or sub_type or "UNKNOWN"
            t = f"SECR: bus protocol violation [{m_name}:{s_name}]: {e}"
            self._logger.crt(t, m_name=m_name, s_name=s_name, e=e)
            return

        try:
            self._outbox.put(frame, block=False)
            self._logger.dbg("send: {frame}", frame=frame)
            res = True
        except Exception as e:
            self._logger.crt("SECR: outbox error (Queue Full/Closed): {e}", e=e)
        return res

    # TODO Do i need it? dont used (was for logger)
    def _log_push(self, evt_type: EvtType, payload: dict[str, list]) -> None:
        """
        Safely send Frame to the Bus for MsgLogger.
        Only for Logger.
        """
        try:
            frame = Frame(
                msg_type=MsgType.EVT,
                sender=self._addr,
                evt_type=evt_type,
                payload=payload
            )
            self._outbox.put(frame, block=False)
        except Exception as e:
            print(f"Critical: [{self._addr.unit}]: Logger transport failed: {e}")

    # --- Internal logic ---

    def _handle_frame(self, incoming: Frame | dict) -> bool:
        """
        Processes a single incoming message.
        Returns True if callback was called.
        """
        self._logger.dbg("SECR: inbox: {incoming}", incoming=incoming)
        # Lazy reconstruction of Frame from network dict using singleton addresses from Broker
        if isinstance(incoming, dict):
            try:
                # Get Frame from dict
                frame = self._resurrect(incoming)
            except Exception as e:
                self._logger.err("SECR: failed to resurrect frame: {e}", e=e)
                return False
        else:
            frame = incoming

        start_ts = perf_counter()
        
        # Dispatch table for message types
        dispatch = {
            MsgType.SYS: self._process_system,
            MsgType.EVT: self._process_event,
            MsgType.CMD: self._process_command,
            MsgType.RPT: self._process_report,
        }
        
        handler = dispatch.get(frame.msg_type)
        if handler:
            res = handler(frame)
        else:
            t = "SECR: Received message with unknown type: {frame}",
            self._logger.err(t, frame=frame)
            return False
            
        self._log_task_duration(perf_counter() - start_ts, frame)
        return res

    def _process_system(self, frame: Frame) -> bool:
        """
        Processes system frames by dispatching to registered callbacks.
        Executes validated handlers with unpacked arguments and logs errors.
        """
        def format_cb(cb):
            """Only for logging: take method, return string-name"""
            if hasattr(cb, "__self__") and hasattr(cb, "__func__"):
                class_name = cb.__self__.__class__.__name__
                method_name = cb.__func__.__name__
                return f"{class_name}.{method_name}"
            if hasattr(cb, "__name__"):
                return cb.__name__
            return str(cb)
        
        callback = self._handlers_sys.get(frame.sys_type, None)
        if not callback:
            t = "SECR: unsupported, income: {frame}"
            self._logger.err(t, frame=frame)
            return False
        if not callable(callback):
            t = "SECR: not callable! cb:{cb}, {frame}"
            self._logger.crt(t, frame=frame, cb=callback)
            return False
        cb_str = format_cb(callback)
        self._logger.dbg("SECR: try call {cb}", cb=cb_str)
        try:
            res = callback(frame)
            self._logger.dbg("SECR: called {cb}, returned:{res}", cb=cb_str, res=res)
            return True
        except Exception as e:
            self._logger.err("SECR: SysCallback error: {e}", e=e)
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
            t = "SECR: Was get evt, but module hasn't subcr {frame}"
            self._logger.err(t, frame=frame)
            return False

    def _process_command(self, frame: Frame) -> bool:
        """
        Processing command subscriptions.
        Command logic: stop, busy and start checks.
        Returns True if callback was called.
        """
        # Only for one-thread modules
        if not self._has_thread_pool and self._module_is_busy:
            self.send_rpt(frame.sender, frame.cmd_id, RptType.CANT_DO, reason=RptReason.MODULE_BUSY)
            return False
        
        # Look for handler
        handler = self._handlers_cmd.get(frame.cmd_type)
        if handler and callable(handler):
            self.send_rpt(frame.sender, frame.cmd_id, RptType.INTO_WORK)
            self._module_is_busy = True 
            self._cmd_in[frame.cmd_id] = {"deadline": frame.deadline, "sender": frame.sender}
            try:
                handler(frame)
            except Exception as e:
                self._logger.err("cant to do callback: {e}")
                self.send_rpt(frame.sender, frame.cmd_id, RptType.CANT_DO, 
                              reason=RptReason.EXEC_EXCEPTION)
            finally:
                self._module_is_busy = False
            return True
        else:
            t = "SECR: Command received, but no handler found {frame}"
            self._logger.err(t, frame=frame)
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
            if frame.cmd_id in self._cmd_expired:
                t = "SECR: Dropping late report for already EXPIRED cmd_id {cmd_id}. Subtype: {rpt}"
                self._logger.wrn(t, cmd_id=frame.cmd_id, rpt=frame.rpt_type.name)
            else:
                t = "SECR: got report with unknowed cmd_id {frame} cmd_out={cmd_out}"
                self._logger.err(t, frame=frame, cmd_out=self._cmd_out)
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

    # TODO Verify the ability to request a deadline extension.
    # TODO Verify the risk of collision between automatic and manual deadline extensions.
    def _check_deadlines(self) -> bool:
        """Validates all time constraints for outgoing and incoming tasks."""
        now = perf_counter()
        was_work = False
        # Check outgoing commands (waiting for Executor to act).
        for cmd_id, info in list(self._cmd_out.items()):
            was_work = True
            rtype = None
            if now > info["deadline_answ"]:   rtype = RptType.REACTION_TIMEOUT
            elif now > info["deadline_done"]: rtype = RptType.EXECUTION_TIMEOUT
            if rtype:
                frame = None
                try:
                    frame = Frame(MsgType.RPT, self._addr, {"text": rtype.value}, 
                                  rpt_type=rtype, cmd_id=cmd_id, recipient=self._addr)
                except ValueError as e:
                    self._logger.err("SECR: Cant create Frame for timeout-cb")
                print(f"unit={self._addr} self._cmd_out={self._cmd_out}, cmd_id={cmd_id}")
                if frame:
                    if now > info["deadline_answ"]:
                        info["cb_timeout_answ"](frame)
                        self._cmd_out.pop(cmd_id)
                        # Save expired ID to history buffer
                        self._cmd_expired.append(cmd_id)
                        if len(self._cmd_expired) > self._config.CMD_HISTORY_LIMIT:
                            self._cmd_expired.pop(0)
                        print("pop1")
                    elif now > info["deadline_done"]:
                        info["cb_timeout_done"](frame)
                        self._cmd_out.pop(cmd_id)
                        # Save expired ID to history buffer
                        self._cmd_expired.append(cmd_id)
                        if len(self._cmd_expired) > self._config.CMD_HISTORY_LIMIT:
                            self._cmd_expired.pop(0)
                        print("pop2")

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
        dur_ms = duration * 1000
        durs = [0.001, 0.01, 0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0]
        i = next((index for index, val in enumerate(durs) if dur_ms < val), len(durs))
        speed = f"speed_{i}"
        t = "SECR: Done {speed}: {dur:.1f}ms {frame}"
        #self._logger.dbg(t, speed=speed, dur=dur_ms, frame=frame)
    
    def _set_unit(self, unit: BaseUnit) -> bool:
        """
        Registers a module object with the secretary to call its methods directly. 
        Only for Kernel.
        """
        if not isinstance(unit, BaseUnit):
            self._logger.err("SECR: set_unit: get not BaseUnit: {unit}", unit=unit)
            return False
        if self._unit is not None:
            self._logger.err("SECR: set_unit: Detected second set! Obj: {unit}", unit=unit)
            return False
        self._unit = unit
        self.auto_subscribe()
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
                            t = "SECR: Bus read limit reached ({readed})"
                            self._logger.wrn(t, readed=readed)
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
