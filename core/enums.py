# core/enum.py
from enum import Enum, unique

class Addr(str, Enum):
    KERNEL = "kernel"
    BUS = "bus",
    ORCHESTRATOR = "orchestrator"
    NETWORK = "network"
    NETWORK_DB = "network_db"
    ENGINE = "engine"

class MsgType(str, Enum):
    COMMAND = "cmd"
    REPORT = "rpt"
    EVENT = "evt"

@unique
class EvtType(str, Enum):
    """EventType for the shared bus"""
    MSG = "msg"
    WRN = "wrn"
    ERR = "err"
    LOG = "log"
    BUS_IS_OVERCROWDED = "bus_is_overcrowded"
    BUFFER_NEW_DATA = "buffer_new_data"

@unique
class CmdType(str, Enum):
    """CommandType for the shared bus"""
    STOP_APP = "stop_app"
    TEST = "test"

class SanapoError(Exception): pass
class AddressBusyError(SanapoError): pass
class MessageTypeError(SanapoError): pass
class UnknownCmdError(SanapoError): pass
class UnknownEvtError(SanapoError): pass
class UnknownRecipientError(SanapoError): pass
