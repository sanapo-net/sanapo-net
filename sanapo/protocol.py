# sanapo/protocol.py
from dataclasses import dataclass
from enum import Enum
from typing import Type
from typing import TYPE_CHECKING

from sanapo.enums import MsgType, SysType, RptType, RptReason, EnumRegistry, MessageInitError
from sanapo.addr import Addr

if TYPE_CHECKING:
    from sanapo.message_broker import MessageBroker

EvtType = Enum
CmdType = Enum

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

        if self.msg_type == MsgType.SYS:
            check_fields('sys_type', 'payload')
        elif self.msg_type == MsgType.CMD:
            check_fields('cmd_type', 'recipient', 'cmd_id', 'payload')
        elif self.msg_type == MsgType.EVT:
            check_fields('evt_type', 'payload')
        elif self.msg_type == MsgType.RPT:
            check_fields('rpt_type', 'recipient', 'cmd_id', 'payload')
            if self.rpt_type == RptType.TIME_EXTENSION_REQUEST:
                check_fields('time_ext_req')
            if self.rpt_type == RptType.CANT_DO:
                if self.reason is None:
                    raise MessageInitError(f"Field 'reason' is mandatory for RptType.CANT_DO")
    
    def to_dict(self, deep: bool = False) -> dict:
        """
        Serializes the frame into a dictionary. 
        If deep=True, recursively converts Enums in payload to values.
        """
        def _deep(obj):
            if isinstance(obj, Enum): return obj.value
            if isinstance(obj, dict): return {k: _deep(v) for k, v in obj.items()}
            if isinstance(obj, (list, tuple, set)): return [_deep(i) for i in obj]
            return obj

        sub_type_obj = self.evt_type or self.sys_type or self.cmd_type or self.rpt_type
        
        data = {
            "msg_type": self.msg_type.value,
            "sender": str(self.sender),
            "payload": _deep(self.payload) if deep else self.payload,
            "sub_type": sub_type_obj.value if sub_type_obj else None
        }

        if self.recipient:    data["recipient"] = str(self.recipient)
        if self.cmd_id:       data["cmd_id"] = self.cmd_id
        if self.reason:       data["reason"] = self.reason.value
        if self.deadline:     data["deadline"] = self.deadline
        if self.time_ext_req: data["time_ext_req"] = self.time_ext_req
        
        return {k: v for k, v in data.items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict, reg: EnumRegistry, broker: MessageBroker, deep: bool = False, 
                  payload_enums: list[Type[Enum]] = None) -> 'Frame':
        """
        Reconstructs a Frame from a dictionary. 
        If deep=True and payload_enums provided, attempts to restore Enums in payload.
        """
        def get_e(enum_cls, val):
            return enum_cls(val) if val is not None else None

        def _resurrect(obj):
            if isinstance(obj, str) and payload_enums:
                for e_cls in payload_enums:
                    try: return e_cls(obj)
                    except ValueError: continue
            if isinstance(obj, dict): return {k: _resurrect(v) for k, v in obj.items()}
            if isinstance(obj, list): return [_resurrect(i) for i in obj]
            return obj

        m_type = MsgType(data["msg_type"])
        sub_val = data.get("sub_type")

        frame = cls(
            msg_type=m_type,
            sender=broker.get_addr(data["sender"]), 
            payload=data.get("payload", {}),
            sys_type=get_e(reg.sys, sub_val) if m_type == MsgType.SYS else None,
            evt_type=get_e(reg.evt, sub_val) if m_type == MsgType.EVT else None,
            cmd_type=get_e(reg.cmd, sub_val) if m_type == MsgType.CMD else None,
            rpt_type=get_e(reg.rpt, sub_val) if m_type == MsgType.RPT else None,
            recipient=broker.get_addr(data["recipient"]) if data.get("recipient") else None,
            cmd_id=data.get("cmd_id"),
            reason=get_e(reg.reason, data.get("reason")),
            deadline=data.get("deadline"),
            time_ext_req=data.get("time_ext_req")
        )
        if deep and payload_enums:
            new_payload = _resurrect(frame.payload)
            object.__setattr__(frame, 'payload', new_payload)

        return frame
    
    @classmethod
    def from_dict_light(cls, data: dict, reg: EnumRegistry, broker: MessageBroker) -> 'Frame':
        """
        Lightweight frame reconstruction. 
        Restores header Enums using the Registry while keeping the payload raw.
        """
        m_type = MsgType(data["msg_type"])
        sub_val = data.get("sub_type")

        # Fast mapping without deep validation of payload structure
        return cls(
            msg_type=m_type,
            sender=broker.get_addr(data["sender"]),
            payload=data.get("payload", {}), # Keep payload as raw dict/data
            sys_type=reg.sys(sub_val) if m_type == MsgType.SYS else None,
            evt_type=reg.evt(sub_val) if m_type == MsgType.EVT else None,
            cmd_type=reg.cmd(sub_val) if m_type == MsgType.CMD else None,
            rpt_type=reg.rpt(sub_val) if m_type == MsgType.RPT else None,
            recipient=broker.get_addr(data.get("recipient")) if data.get("recipient") else None,
            cmd_id=data.get("cmd_id"),
            reason=reg.reason(data.get("reason")) if data.get("reason") else None,
            deadline=data.get("deadline"),
            time_ext_req=data.get("time_ext_req")
        )

