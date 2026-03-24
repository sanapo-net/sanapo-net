# core/protocol.py
from dataclasses import dataclass
from typing import Optional, Any, Union
from core.enums import MsgType, Addr

@dataclass(frozen=True)
class Frame:
    """
    Universal message frame for the system bus.

    The 'frozen=True' parameter makes the instance immutable,
    preventing accidental data modification during dispatching.
    """
    # Mandatory fields
    msg_type: MsgType
    sender: Addr

    # Optional fields (must have default values and follow mandatory ones)
    recipient: Addr = None
    payload: Any = None
    cmd_id: Optional[str] = None
    evt: Optional[str] = None
    cmd: Optional[str] = None
