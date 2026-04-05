# core/protocol.py
from dataclasses import dataclass
from typing import Optional, Any
from core.enums import MsgType, Addr, RptType, MessageInitError

@dataclass(frozen=True)
class Frame:
    """
    Universal message frame for the system bus.

    The 'frozen=True' parameter makes the instance immutable,
    preventing accidental data modification during dispatching.
    """
    # TODO add EvtType, CmdType, RptType, SysType
    msg_type: MsgType
    sender: Addr
    sys_type: Optional[str] = None
    evt_type: Optional[str] = None
    cmd_type: Optional[str] = None
    rpt_type: Optional[str] = None
    recipient: Optional[Addr] = None
    cmd_id: Optional[str] = None
    deadline: Optional[float] = None
    time_ext_req: Optional[float] = None
    reason: Optional[str] = None
    payload: Any = None # : dict

    def __post_init__(self):
        if not isinstance(self.msg_type, MsgType):
            raise MessageInitError(f"msg_type must be MsgType, not {type(self.msg_type)}")
        if not isinstance(self.sender, Addr):
            raise MessageInitError(f"sender must be Addr, not {type(self.sender)}")

        def check_fields(*fields):
            for field in fields:
                if getattr(self, field) is None:
                    raise MessageInitError(f"Field '{field}' is mandatory for {self.msg_type}")

        if self.msg_type == MsgType.COMMAND:
            check_fields('cmd_type', 'recipient', 'cmd_id')
        elif self.msg_type == MsgType.EVENT:
            check_fields('evt_type')
        elif self.msg_type == MsgType.REPORT:
            check_fields('rpt_type', 'recipient', 'cmd_id')
            if self.rpt_type == RptType.TIME_EXTENSION_REQUEST:
                check_fields('time_ext_req')
            if self.rpt_type == RptType.CANT_DO:
                if self.reason is None:
                    raise MessageInitError(f"Field 'reason' is mandatory for RptType.CANT_DO")

