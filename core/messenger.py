# core/messenger.py
from core import enums
from core.protocol import Frame

DEFAULT_CMD_TIMEOUT = 5.0 # seconds

class Messenger:
    """
    Module interface for system interactions.
    Handles command tracking, report routing, and event publishing
    using the Frame protocol.
    """

    def __init__(self, address: enums.Addr, bus, orchestrator):
        self.address = address
        self._bus = bus
        self._orch = orchestrator
        self._counter = 0
        self._command_handlers = {}  # {CmdType: function, ...}
        self._event_handlers = {}    # {EvtType: function, ...}
        self._pending_reports = {}   # {cmd_id: {callback, timeout_cb, expire_at}, ...}

    def send_cmd(
            self,
            recipient: enums.Addr,
            cmd_type: enums.CmdType,
            payload = None,
            on_report = None,
            on_timeout = None,
            timeout = DEFAULT_CMD_TIMEOUT
        ):
        """
        Send a command, payload, callbacks and track its report with a timeout.
        Called only by the a module.
        """
        self._counter += 1
        cmd_id = f"{self.address}_{self._counter}"

        # Use orchestrator's loop time for precise tracking
        now = self._orch.loop.time() if self._orch.loop else 0

        self._pending_reports[cmd_id] = {
            "callback": on_report,
            "timeout_cb": on_timeout,
            "expire_at": now + timeout,
            "payload": payload
        }

        # Pack data into a Frame object
        frame = Frame(
            msg_type = enums.MsgType.COMMAND,
            sender = self.address,
            recipient = recipient,
            cmd = cmd_type,
            cmd_id = cmd_id,
            payload = payload
        )
        self._bus.send(frame)

    def send_evt(self, event_type: enums.EvtType, payload = None):
        """
        Broadcast an event to the bus.
        Called only by the a module.
        """
        frame = Frame(
            msg_type = enums.MsgType.EVENT,
            sender = self.address,
            evt = event_type,
            payload = payload
        )
        self._bus.send(frame)

    def send_rpt(self, recipient: enums.Addr, cmd_id: str, payload = None):
        """
        Reply to a command with a report frame.
        Called only by the a module.
        """
        frame = Frame(
            msg_type = enums.MsgType.REPORT,
            sender = self.address,
            recipient = recipient,
            cmd_id = cmd_id,
            payload = payload
        )
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


    def _handle_incoming_command(self, msg):
        """
        Internal: Handles an incoming command from the Bus.
        Called only by the Orchestrator.
        """
        cmd_type = msg.cmd
        handler = self._command_handlers.get(cmd_type)
        if handler:
            # Call command-callback of module (take it from _command_handlers)
            handler(msg)
        else:
            raise enums.UnknownCmdError(f"UnknownCmdError: {cmd_type}")   

    def _handle_incoming_event(self, msg):
        """
        Internal: Handles an incoming event from the Bus.
        Called only by the Orchestrator.
        """
        evt_type = msg.evt
        handler = self._event_handlers.get(evt_type)
        if handler:
            # Call event-callback of module (take it from _command_handlers)
            handler(msg)
        else:
            raise enums.UnknownEvtError(f"UnknownCmdError: {evt_type}") 

    def _handle_incoming_report(self, msg: Frame):
        """
        Internal: Handles an incoming report from the Bus.
        Called only by the Orchestrator.
        """
        cmd_id = msg.cmd_id
        if cmd_id in self._pending_reports:
            entry = self._pending_reports.pop(cmd_id)
            if entry["callback"]:
                # Execute callback via thread pool
                self._orch._dispatch(entry["callback"], msg)

    def _check_timeouts(self, now: float):
        """
        Check all pending commands against current loop time.
        Called only by the Orchestrator.
        """
        # list() is used to allow dictionary modification during iteration
        for cmd_id, entry in list(self._pending_reports.items()):
            if now > entry["expire_at"]:
                self._pending_reports.pop(cmd_id)
                if entry["timeout_cb"]:
                    # Dispatch timeout notice
                    self._orch._dispatch(entry["timeout_cb"], entry["payload"])

