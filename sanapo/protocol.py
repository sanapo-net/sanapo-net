# sanapo/protocol.py
from dataclasses import dataclass
from enum import Enum
from typing import Type

from sanapo.enums import MsgType, SysType, RptType, MessageInitError, RptReason
from sanapo.addr import Addr

EvtType = Enum
CmdType = Enum


@dataclass
class EnumRegistry:
    addr: Type[Enum]
    sys: Type[Enum]
    evt: Type[Enum]
    cmd: Type[Enum]
    rpt: Type[Enum]
    reason: Type[Enum]


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
    reason: RptReason | None = None

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

    def to_dict(self) -> dict:
        """Serializing a frame into a dictionary for JSON logging."""
        data = {
            "msg_type": self.msg_type.value,
            "sender": self.sender.value,
            "sub_type": (self.evt_type or self.sys_type or self.cmd_type or self.rpt_type).value,
        }
        if self.cmd_id: data["id"] = self.cmd_id
        if self.reason: data["reason"] = self.reason.value
        if self.recipient: data["recipient"] = self.recipient.value
        if self.payload:
            if "text" in self.payload:
                data["text"] = self.payload["text"]
            data["payload"] = self.payload 
        return data
    
    def from_dict(cls, data: dict, reg: EnumRegistry) -> 'Frame':
        pass
