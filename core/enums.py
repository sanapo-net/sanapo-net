# core/enums.py
# ToDo: in future all replacy as auto()
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
    EVT_TEST = "evt_test"
    MSG = "msg"
    WRN = "wrn"
    ERR = "err"
    LOG = "log"
    BUS_IS_OVERCROWDED = "bus_is_overcrowded"
    ICMP_RAW_DATA_READY = "icmp_raw_data_ready"
    ICMP_TICK_DATA_READY = "icmp_tick_data_ready"
    ICMP_DB_DATA_READY = "icmp_db_data_ready"
    ICMP_1M_DATA_READY = "icmp_1m_data_ready"
    ICMP_3M_DATA_READY = "icmp_3m_data_ready"
    ICMP_10M_DATA_READY = "icmp_10m_data_ready"
    TICK_05 = "tick_05"
    TICK_1 = "tick_1"
    TICK_2 = "tick_2"
    TICK_4 = "tick_4"
    TICK_8 = "tick_8"
    TICK_24 = "tick_24"
    TICK_120 = "tick_120"
    TICK_600 = "tick_600"


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
    TIME_EXTENSION_REQUEST = "time_extension_request"
    CANT_DO = "cant_do"

@unique
class RptReason(str, Enum):
    """For CANT_DO and TIME_EXTENSION_REQUEST"""
    OK = "OK"
    SEE_PAYLOAD = "SEE_PAYLOAD"
    
    # Rejection reasons (CANT_DO)
    MODULE_BUSY = "MODULE_BUSY"         # Single-threaded module is occupied
    INVALID_ARGS = "INVALID_ARGS"       # Command payload is corrupted or invalid
    RESOURCE_LOCKED = "RESOURCE_LOCKED" # Hardware or file is busy
    INTERNAL_ERROR = "INTERNAL_ERROR"   # Unhandled exception in module

class SanapoError(Exception): pass
class AddressBusyError(SanapoError): pass
class MessageTypeError(SanapoError): pass
class MessageInitError(SanapoError): pass
class UnknownCmdError(SanapoError): pass
class UnknownEvtError(SanapoError): pass
class UnknownRptError(SanapoError): pass
class UnknownRecipientError(SanapoError): pass
