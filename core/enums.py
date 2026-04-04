# core/enums.py
from enum import Enum, unique


class RollWin(int, Enum):
    MIN_1  = 60
    MIN_3  = 180 
    MIN_10 = 600


@unique
class TickInterval(float, Enum):
    """Physical time constants in seconds."""
    OFF      = -1
    SEC_05   = 0.5
    SEC_1    = 1.0
    SEC_2    = 2.0
    SEC_4    = 4.0
    SEC_8    = 8.0
    SEC_24   = 24.0
    SEC_120  = 120.0
    SEC_600  = 600.0


class Addr(str, Enum):
    KERNEL = "kernel"
    BUFFER_ICMP = "buffer_icmp"
    BUFFER_TCP = "buffer_tcp"
    BUFFER_DISCOVERY = "buffer_discovery"
    SETTINGS_ICMP = "settings_icmp"
    SETTINGS_PORTS = "settings_ports"
    SETTINGS_SNIFFER = "settings_sniffer"
    SETTINGS_GATE = "settings_gate"
    SETTINGS_UI = "settings_ui"
    SETTINGS_DB = "settings_db"


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
    ERR_LOGIC = "err_logic" # not users error
    BUS_IS_OVERCROWDED = "bus_is_overcrowded"
    ICMP_RAW_READY = "icmp_raw_ready"
    ICMP_TICK_READY = "icmp_tick_ready"
    ICMP_AGR_WIN_1M_READY = "icmp_agr_win_1m_ready"
    ICMP_AGR_WIN_3M_READY = "icmp_agr_win_3m_ready"
    ICMP_AGR_WIN_10M_READY = "icmp_agr_win_10m_ready"
    ICMP_AGR_DB_10M_READY = "icmp_agr_db_10m_ready"
    ICMP_RAW_DB_10M_READY = "icmp_raw_db_10m_ready"
    TICK_05 = "tick_05"
    TICK_1 = "tick_1"
    TICK_2 = "tick_2"
    TICK_4 = "tick_4"
    TICK_8 = "tick_8"
    TICK_24 = "tick_24"
    TICK_120 = "tick_120"
    TICK_10M = "tick_10m" # every calendar 10min (system time)
    NETWORK_NEW_VER = "network_new_ver"


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
