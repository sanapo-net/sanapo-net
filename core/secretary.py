# core/secretary.py
import time
import threading
from queue import Empty
from typing import Callable, Any, Optional, Dict

from core import enums
from core.protocol import Frame

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

    def __init__(self, address: enums.Addr, tools):
        self.address = address
        self._inbox = tools.inbox      # Read-only queue from Kernel
        self._outbox = tools.outbox    # Write-only queue to Kernel
        self.settings = tools.settings
        self._cmd_counter = 0
        self._handlers_cmd: Dict[enums.CmdType, Callable] = {}
        self._handlers_evt: Dict[enums.EvtType, Callable] = {}
        
        # Commands sent by this Massenger (as Commander)
        self._pending_out = {} # {cmd_id: {callbacks, deadlines, recipient, payload}}
        
        # Commands received by this Massenger (as Executor)
        self._pending_in = {}  # {cmd_id: {deadline, sender}}

        self._is_running = False
        self._thread: Optional[threading.Thread] = None

    # Lifecycle management

    def start(self):
        """Starts the background worker for message processing and deadline checks."""
        if not self._is_running:
            self._is_running = True
            self._thread = threading.Thread(target=self._worker_loop, daemon=True)
            self._thread.start()

    def stop(self):
        """Stops the secretary's background thread."""
        self._is_running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def process_once(self):
        """Single pass through the inbox and deadline checks (for sync or async calls)."""
        self._read_inbox()
        self._check_deadlines()

    def _worker_loop(self):
        """
        Internal background loop with time compensation.
        Ensures stable tick rate regardless of logic execution time.
        """
        while self._is_running:
            # Fixed Timestep Loop
            start_time = time.perf_counter()
            self.process_once()
            work_duration = time.perf_counter() - start_time
            sleep_time = self.settings.SECRETARY_TICK_RATE - work_duration
            if sleep_time > 0:
                time.sleep(sleep_time)

    # Subscriptions

    def subscribe(self,
            cb: Callable,
            cmd_type: enums.CmdType = None,
            evt_type: enums.EvtType = None
        ):
        """Register a callback for a specific command or event type."""
        if cmd_type: self._handlers_cmd[cmd_type] = cb
        if evt_type: self._handlers_evt[evt_type] = cb

    def unsubscribe(self, cmd_type: enums.CmdType = None, evt_type: enums.EvtType = None):
        """Remove a previously registered callback."""
        if cmd_type: self._handlers_cmd.pop(cmd_type, None)
        if evt_type: self._handlers_evt.pop(evt_type, None)

    def configure_subscriptions(self,
            events: Dict[enums.EvtType, Callable] = None, 
            commands: Dict[enums.CmdType, Callable] = None
        ):
        """Batch register multiple handlers using dictionaries."""
        if events: self._handlers_evt.update(events)
        if commands: self._handlers_cmd.update(commands)

    # Outgoing messages

    def send_evt(self, evt_type: enums.EvtType, payload: Any = None):
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
            cb_done=None,
            cb_canttodo=None,
            cb_timeout_answ=None,
            cb_timeout_done=None,
            cb_time_ext_req=None,
            deadline_answ_dur=None,
            deadline_done_dur=None,
            payload=None
        ):
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
        d_answ = now + (deadline_answ_dur or self.settings.DEFAULT_CMD_DEADLINE_ANSW)
        d_done = now + (deadline_done_dur or self.settings.DEFAULT_CMD_DEADLINE_DONE)

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
            payload: Any = None,
            time_ext_req: float = None
        ):
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
            self._pending_in.pop(cmd_id, None)

        # Clean up tracking if the task is finished from our side
        if rpt_type in [enums.RptType.DONE, enums.RptType.CANT_DO]:
            self._pending_in.pop(cmd_id, None)

    def modify_deadline(self, cmd_id: str, add_to_deadline: float):
        """Allows a commander to adjust the deadline of an active command."""
        if cmd_id in self._pending_out:
            if add_to_deadline == self.FAIL:
                self._pending_out[cmd_id]["deadline_done"] = -1.0
            elif add_to_deadline == self.EVER:
                self._pending_out[cmd_id]["deadline_done"] = float('inf')
            else:
                self._pending_out[cmd_id]["deadline_done"] += add_to_deadline

    # Internal logic

    def _read_inbox(self):
        """Fetches messages from the personal module inbox."""
        try:
            while not self._inbox.empty():
                frame = self._inbox.get_nowait()
                self._handle_frame(frame)
        except Empty:
            pass

    def _handle_frame(self, frame: Frame):
        """Processes a single incoming frame."""
        now = time.perf_counter()

        if frame.msg_type == enums.MsgType.EVENT:
            handler = self._handlers_evt.get(frame.evt_type)
            if handler: handler(frame)

        elif frame.msg_type == enums.MsgType.COMMAND:
            # Secretary automatically replies with INTO_WORK as a handshake
            self.send_rpt(frame.sender, frame.cmd_id, enums.RptType.INTO_WORK)
            
            # Monitor this command for automatic TIME_EXTENSION_REQUEST requests
            self._pending_in[frame.cmd_id] = {
                "deadline": frame.deadline or (now + 1.0),
                "sender": frame.sender
            }
            
            handler = self._handlers_cmd.get(frame.cmd_type)
            if handler: 
                handler(frame)
            else: 
                print(f"[Secretary] Warning: no handler for {frame.cmd_type}")

        elif frame.msg_type == enums.MsgType.REPORT:
            self._handle_report(frame)

    def _handle_report(self, frame: Frame):
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

        elif frame.rpt_type == enums.RptType.GIVE_ME_TIME:
            if frame.time_ext_req:
                info["deadline_done"] += frame.time_ext_req
            info["cb_time_ext_req"](frame)

    def _check_deadlines(self):
        """Validates all time constraints for outgoing and incoming tasks."""
        now = time.perf_counter()

        # 1. Check outgoing commands (waiting for Executor to act)
        for cmd_id, info in list(self._pending_out.items()):
            if now > info["deadline_answ"]:
                info["cb_timeout_answ"]({"cmd_id": cmd_id, "reason": "Reaction Timeout"})
                self._pending_out.pop(cmd_id)
            elif now > info["deadline_done"]:
                info["cb_timeout_done"]({"cmd_id": cmd_id, "reason": "Execution Timeout"})
                self._pending_out.pop(cmd_id)

        # 2. Automatic deadline extension (when we are the Executor)
        # If remaining time is below threshold - automatically request more time
        threshold = self.settings.DEADLINE_EXTENSION_THRESHOLD 
        for cmd_id, info in list(self._pending_in.items()):
            if info["deadline"] - now < threshold:
                extension = self.settings.DEFAULT_TIME_EXTENSION
                self.send_rpt(
                    info["sender"],
                    cmd_id,
                    enums.RptType.TIME_EXTENSION_REQUEST,
                    time_ext_req=extension
                )
                info["deadline"] += extension
