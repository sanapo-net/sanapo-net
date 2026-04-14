# core/protocol.py
from dataclasses import dataclass
from enums import Addr, MsgType, EvtType, CmdType, SysType, RptType, MessageInitError

@dataclass(frozen=True)
class Frame:
    """
    Universal message frame for the system bus.

    The 'frozen=True' parameter makes the instance immutable,
    preventing accidental data modification during dispatching.
    """

    msg_type: MsgType
    sender: Addr
    payload: dict[str, any]
    sys_type: SysType | None = None
    evt_type: EvtType | None = None
    cmd_type: CmdType | None = None
    rpt_type: RptType | None = None
    recipient: Addr | None = None
    cmd_id: str | None = None
    deadline: float | None = None
    time_ext_req: float | None = None
    reason: str | None = None

    def __post_init__(self):
        if not isinstance(self.msg_type, MsgType):
            raise MessageInitError(f"msg_type must be MsgType, not {type(self.msg_type)}")
        if not isinstance(self.sender, Addr):
            raise MessageInitError(f"sender must be Addr, not {type(self.sender)}")

        def check_fields(*fields):
            for field in fields:
                if getattr(self, field) is None:
                    raise MessageInitError(f"Field '{field}' is mandatory for {self.msg_type}")

        if self.msg_type == MsgType.SYSTEM:
            check_fields('sys_type', 'payload')
        elif self.msg_type == MsgType.COMMAND:
            check_fields('cmd_type', 'recipient', 'cmd_id', 'payload')
        elif self.msg_type == MsgType.EVENT:
            check_fields('evt_type', 'payload')
        elif self.msg_type == MsgType.REPORT:
            check_fields('rpt_type', 'recipient', 'cmd_id', 'payload')
            if self.rpt_type == RptType.TIME_EXTENSION_REQUEST:
                check_fields('time_ext_req')
            if self.rpt_type == RptType.CANT_DO:
                if self.reason is None:
                    raise MessageInitError(f"Field 'reason' is mandatory for RptType.CANT_DO")

