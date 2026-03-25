# core/messenger.py
from core import enums
from core.protocol import Frame

DEFAULT_CMD_DEADLINE_ANSW = 0.05 # seconds
DEFAULT_CMD_DEADLINE_DONE = 0.8 # seconds

class Messenger:
    """
    Module interface for system interactions.
    Handles command tracking, report routing, and event publishing
    using the Frame protocol.
    """

    # Semantic constants for deadline management
    KEEP = 0.0          # No change to current deadline
    FAIL = -float('inf')# Task expires immediately (lower than any current time)
    EVER = float('inf') # Task never expires (higher than any current time)

    def __init__(self, address: enums.Addr, bus, orchestrator):
        self.address = address
        self._bus = bus
        self._orch = orchestrator
        self._cmd_counter = 0
        self._command_handlers = {}  # {CmdType: function, ...}
        self._event_handlers = {}    # {EvtType: function, ...}
        self._pending_reports = {}   # {cmd_id: {callback, timeout_cb, expire_at}, ...}

    def send_cmd(
            self,
            recipient: enums.Addr,
            cmd_type: enums.CmdType,
            cb,
            cb_done = None,
            cb_canttodo = None,
            cb_timeout_answ = None,
            cb_timeout_done = None,
            cb_givemetime = None,
            deadline_answ_dur = DEFAULT_CMD_DEADLINE_ANSW,
            deadline_done_dur = DEFAULT_CMD_DEADLINE_DONE,
            payload = None
        ):
        """
        Send a command, payload, callbacks and track its report with a timeout.
        Called only by the a module.
        """
        self._cmd_counter += 1
        cmd_id = f"{self.address}_{self._cmd_counter}"
        
        cb_done = cb_done or cb
        cb_canttodo = cb_canttodo or cb
        cb_timeout_answ = cb_timeout_answ or cb
        cb_timeout_done = cb_timeout_done or cb
        cb_givemetime = cb_givemetime or cb

        # Use orchestrator's loop time for precise tracking
        now = self._orch.loop.time() if self._orch.loop else 0
        deadline_answ = now + deadline_answ_dur
        deadline_done = now + deadline_done_dur

        self._pending_reports[cmd_id] = {
            "recipient": recipient,
            "cb_done": cb_done,
            "cb_canttodo": cb_canttodo,
            "cb_timeout_answ": cb_timeout_answ,
            "cb_timeout_done": cb_timeout_done,
            "cb_givemetime": cb_givemetime,
            "deadline_answ": deadline_answ,
            "deadline_done": deadline_done,
            "payload": payload
        }

        # Pack data into a Frame object
        frame = Frame(
            msg_type = enums.MsgType.COMMAND,
            cmd_type = cmd_type,
            sender = self.address,
            recipient = recipient,
            cmd_id = cmd_id,
            payload = payload,
            deadline_done = deadline_done
        )
        self._bus.send(frame)

    def send_evt(self, event_type: enums.EvtType, payload = None):
        """
        Broadcast an event to the bus.
        Called only by the a module.
        """
        frame = Frame(
            msg_type = enums.MsgType.EVENT,
            evt_type = event_type,
            sender = self.address,
            payload = payload
        )
        self._bus.send(frame)

    def send_rpt(
            self,
            rpt_type: enums.RptType,
            recipient: enums.Addr,
            cmd_id: str,
            givemetime = None,
            payload = None
        ):
        """
        Reply to a command with a report frame.
        Called only by the a module.
        """
        frame = Frame(
            msg_type = enums.MsgType.REPORT,
            rpt_type = rpt_type,
            sender = self.address,
            recipient = recipient,
            cmd_id = cmd_id,
            payload = payload
        )
        if rpt_type == enums.RptType.GIVE_ME_TIME:
            frame.givemetime = givemetime
        self._bus.send(frame)

    def setup_handlers(self, events: dict = None, commands: dict = None, ):
        """
        It like instructions for the secretary.
        Called only by the a module.
        """
        if commands:
            self._command_handlers.update(commands)
        if events:
            self._event_handlers.update(events)

    def subscribe(self, cb, cmd_type: enums.CmdType = None, evt_type: enums.EntType = None):
        """
        Register a callback for a event or a command.
        Called only by the a module.
        """
        if cmd_type:
            self._command_handlers[cmd_type] = cb
        elif evt_type:
            self._event_handlers[evt_type] = cb

    def unsubscribe(self, cmd_type: enums.CmdType = None, evt_type: enums.EntType = None):
        """
        Unregister a callback for a command or an event.
        Removes the instruction from the secretary's folders.
        Called only by the a module.
        """
        if cmd_type and cmd_type in self._command_handlers:
            del self._command_handlers[cmd_type]
            
        elif evt_type and evt_type in self._event_handlers:
            del self._event_handlers[evt_type]

    def modify_deadline(self, cmd_id: str, add_to_deadline: float):
        """
        Adjusts the command deadline:
        - float: Adds specified seconds to the current deadline.
        - FAIL: Cancels the task; Messenger triggers the timeout-callback immediately.
        - EVER: Messenger waits for the report indefinitely.
        - KEEP: No changes are made to the current deadline.
        """
        if cmd_id in self._pending_reports:
            self._pending_reports[cmd_id]["deadline_done"] += add_to_deadline

    def _send_cancel_task(self, recipient: enums.Addr, cmd_id: str):
        frame = Frame(
            msg_type = enums.MsgType.COMMAND,
            cmd_type = enums.CmdType.CANCEL_TASK,
            sender = self.address,
            recipient = recipient,
            cmd_id = cmd_id
        )
        self._bus.send(frame)


    def _handle_incoming_command(self, msg):
        """
        Internal: Handles an incoming command from the Bus.
        Called only by the Orchestrator.
        """
        handler = self._command_handlers.get(msg.cmd_type)
        if handler:
            # Call command-callback of module (take it from _command_handlers)
            handler(msg)
        else:
            raise enums.UnknownCmdError(f"UnknownCmdError: {msg.cmd_type}")   

    def _handle_incoming_event(self, msg):
        """
        Internal: Handles an incoming event from the Bus.
        Called only by the Orchestrator.
        """
        handler = self._event_handlers.get(msg.evt_type)
        if handler:
            # Call event-callback of module (take it from _command_handlers)
            handler(msg)
        else:
            raise enums.UnknownEvtError(f"UnknownCmdError: {msg.evt_type}") 

    def _handle_incoming_report(self, msg: Frame):
        """
        Internal: Handles an incoming report from the Bus.
        Called only by the Orchestrator.
        """
        cmd_id = msg.cmd_id
        if cmd_id in self._pending_reports:
            entry = self._pending_reports.pop(cmd_id)
            data = {"payload": entry["payload"], "msg": msg}
            if msg.rpt_type == enums.RptType.INTO_WORK:
                entry["deadline_answ"] = Messenger.EVER

            elif msg.rpt_type == enums.RptType.GIVE_ME_TIME:
                data["call_reason"] = "givemetime"
                self._orch._dispatch(entry["cb_givemetime"], data)

            elif msg.rpt_type == enums.RptType.DONE:
                data["call_reason"] = "done"
                self._orch._dispatch(entry["cb_done"], data)
                entry = self._pending_reports.pop(cmd_id)

            elif msg.rpt_type == enums.RptType.CANT_TO_DO:
                data["call_reason"] = "canttodo"
                self._orch._dispatch(entry["cb_canttodo"], data)
                entry = self._pending_reports.pop(cmd_id)

            else:
                raise enums.UnknownRptError(f"UnknownRptError: {msg.rpt_type}") 

    def _check_timeouts(self, now: float):
        """
        Check all pending commands against current loop time.
        Called only by the Orchestrator.
        """
        for cmd_id, entry in list(self._pending_reports.items()):
            for key, cb in [("deadline_answ", "cb_timeout"), ("deadline_done", "cb_done")]:
                if now > entry[key]:
                    self._pending_reports.pop(cmd_id)
                    self._send_cancel_task(entry["recipient"], cmd_id)
                    self._orch._dispatch(entry[cb], {"call_reason": key, "cmd_id": cmd_id, **entry})
                    break
