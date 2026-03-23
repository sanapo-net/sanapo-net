# core/protocol.py
from dataclasses import dataclass
from typing import Optional, Any, Union
from core.enums import MsgType, Addr

# Type aliases for flexibility: allows both Enum members and raw strings
Address = Union[Addr, str]
MessageType = Union[MsgType, str]

@dataclass(frozen=True)
class Frame:
    """
    Universal message frame for the system bus.

    The 'frozen=True' parameter makes the instance immutable,
    preventing accidental data modification during dispatching.
    """

    # Mandatory fields
    msg_type: MessageType
    sender: Address

    # Optional fields (must have default values and follow mandatory ones)
    recipient: Optional[Address] = None
    payload: Any = None
    cmd_id: Optional[str] = None
    evt: Optional[str] = None
    cmd: Optional[str] = None
