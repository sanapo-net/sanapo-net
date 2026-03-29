# core/enums.py
from enum import Enum, unique

class Addr(str, Enum):
    KERNEL = "kernel"
    BUFFER = "buffer"
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
    EVT_TEST = "evt_test"

@unique
class CmdType(str, Enum):
    """CommandType for the shared bus"""
    APP_STOP = "app_stop"
    CANCEL_TASK = "cancel_task"
    CMD_TEST = "cmd_test"

@unique
class RptType(str, Enum):
    """CommandType for the shared bus"""
    DONE = "done"
    INTO_WORK = "into_work"
    TIME_EXTENSION_REQUEST = "time_ext_req"
    CANT_DO = "cant_do"

class SanapoError(Exception): pass
class AddressBusyError(SanapoError): pass
class MessageTypeError(SanapoError): pass
class MessageInitError(SanapoError): pass
class UnknownCmdError(SanapoError): pass
class UnknownEvtError(SanapoError): pass
class UnknownRptError(SanapoError): pass
class UnknownRecipientError(SanapoError): pass
