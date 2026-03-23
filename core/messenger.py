# core/messenger.py
from core.enums import Addr, MsgType, CmdType, EvtType
from core.protocol import Frame

DEFAULT_CMD_TIMEOUT = 5.0 # seconds

class Messenger:
    """
    Module interface for system interactions.
    Handles command tracking, report routing, and event publishing
    using the Frame protocol.
    """

    def __init__(self, address: Addr, bus, orchestrator):
        self.address = address
        self._bus = bus
        self._orch = orchestrator
        self._counter = 0
        self._pending_reports = {} # {cmd_id: {callback, timeout_cb, expire_at}}

    def send_cmd(
            self,
            recipient: Addr,
            cmd_type: CmdType,
            payload = None,
            on_report = None,
            on_timeout = None,
            timeout = DEFAULT_CMD_TIMEOUT
        ):
        """Send a command and track its report with a timeout."""
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
            msg_type = MsgType.COMMAND,
            sender = self.address,
            recipient = recipient,
            cmd = cmd_type,
            cmd_id = cmd_id,
            payload = payload
        )
        self._bus.send(frame)

    def send_evt(self, event_type: EvtType, payload = None):
        """Broadcast an event to the bus."""
        frame = Frame(
            msg_type = MsgType.EVENT,
            sender = self.address,
            event = event_type,
            payload = payload
        )
        self._bus.send(frame)

    def send_rpt(self, recipient: Addr, cmd_id: str, payload = None):
        """Reply to a command with a report frame."""
        frame = Frame(
            msg_type = MsgType.REPORT,
            sender = self.address,
            recipient = recipient,
            cmd_id = cmd_id,
            payload = payload
        )
        self._bus.send(frame)

    def subscribe(self, event_type: EvtType, callback):
        """Register a callback for a specific event type."""
        self._orch.subscribe(event_type, callback)

    def mass_subscribe(self, callbacks: dict):
        """Register callbacks for a specific event type."""
        for event_type, callback in callbacks:
            self._orch.subscribe(event_type, callback)

    def incoming_report_reaction(self, msg: Frame):
        """Route incoming report to the original command callback."""
        cmd_id = msg.cmd_id
        if cmd_id in self._pending_reports:
            entry = self._pending_reports.pop(cmd_id)
            if entry["callback"]:
                # Execute callback via thread pool
                self._orch.dispatch(entry["callback"], msg)

    def check_timeouts(self, now: float):
        """Check all pending commands against current loop time."""
        # list() is used to allow dictionary modification during iteration
        for cmd_id, entry in list(self._pending_reports.items()):
            if now > entry["expire_at"]:
                self._pending_reports.pop(cmd_id)
                if entry["timeout_cb"]:
                    # Dispatch timeout notice
                    self._orch.dispatch(entry["timeout_cb"], entry["payload"])
