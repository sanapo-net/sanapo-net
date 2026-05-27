# transport/adapters/email.py
from __future__ import annotations
import json
from typing import TYPE_CHECKING

from sanapo.transport.adapters import BaseAdapterTransport
from sanapo.enums import TranspReadStat, MsgType, SysType
from sanapo.protocol import Frame

if TYPE_CHECKING:
    from sanapo.transport.services.email import EmailService
    from sanapo.addr import Addr

class EmailAdapterTransport(BaseAdapterTransport):
    """
    Delayed transport via SMTP/IMAP. 
    Supports both Native (JSON) and Export (Text) modes.
    """
    def __init__(self, sanapo_addr: Addr, email: str, service: EmailService, 
                 is_native: bool = False):
        super().__init__(sanapo_addr=sanapo_addr, spec_addr=email, is_native=is_native)
        self._service = service

    def send(self, frame: Frame) -> bool:
        """Encapsulates Frame into an Email and sends via EmailService."""
        try:
            # Generate human-readable subject
            msg_type = frame.msg_type.name
            sub_type = (frame.evt_type or frame.sys_type or frame.cmd_type or frame.rpt_type)
            subject = f"SANAPO: {msg_type}.{sub_type} from {frame.sender}"

            # Prepare body depending on mode
            body = self._frame_to_spec(frame)
            
            return self._service.send_outgoing(self.spec_addr, subject, body)
        except Exception:
            return False

    def read(self) -> dict[str, any]:
        """Pulls the latest email and tries to parse it as a Frame."""
        try:
            raw_data = self._service.get_latest_for(self.spec_addr)
            if not raw_data:
                return {"frame": None, "stat": TranspReadStat.EMPTY, "raw": None}
            
            # Try to reconstruct the frame
            frame = self._spec_to_frame(raw_data)
            return {"frame": frame, "stat": TranspReadStat.OK, "raw": raw_data}
            
        except Exception as e:
            return {"frame": None, "stat": TranspReadStat.CORRUPTED, "raw": str(e)}

    def is_empty(self) -> bool:
        """Checks if there are new unread emails."""
        return not self._service.has_new(self.spec_addr)

    def is_ready(self) -> bool:
        """Checks if the email service connection is active."""
        return self._service.check_connection()

    # TODO update it
    def _frame_to_spec(self, frame: Frame) -> str:
        """Converts Frame to string (JSON for Native, Text for Export)."""
        if self.is_native:
            # Full JSON dump for robot-to-robot communication
            return json.dumps(frame.to_dict(), ensure_ascii=False)
        
        # Human-readable format for Export mode
        return f"Message from {frame.sender}\nContent: {frame.payload}"

    # TODO update it
    def _spec_to_frame(self, raw_data: str) -> Frame:
        """Deserializes raw string data back into a Frame."""
        try:
            # Try to parse as native sanapo JSON
            data_dict = json.loads(raw_data)
            return Frame.from_dict(data_dict)
        except Exception:
            # If failed, wrap raw text into a generic EVENT Frame
            return Frame(
                msg_type=MsgType.SYS, # TODO
                evt_type=SysType.RAW, # TODO
                sender=self.sanapo_addr, # In real life, we'd use a specific Gateway Addr here
                payload={"raw_text": raw_data},
            )
