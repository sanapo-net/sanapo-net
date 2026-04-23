# sanapo/enums.py
from enum import Enum, IntEnum, unique

@unique
class Logs(str, Enum):
    CRT = "crt"
    ERR = "err",
    WRN = "wrn",
    INF = "inf",
    DBG = "dbg"

@unique
class ShutdownTier(IntEnum):
    """
    Defines the order of service lifecycle.
    Startup follows ascending order (1 -> 5).
    Shutdown follows descending order (5 -> 1).
    """
    CORE = 1         # Essential system components. Start first, stop last.
    BASE = 2         # Shared resources and internal services.
    INTEGRATION = 3  # External connections and drivers.
    APPLICATION = 4  # Main business logic.
    EXTENSION = 5    # High-level plugins and UI. Start last, stop first.

@unique
class MsgType(str, Enum):
    COMMAND = "cmd"
    REPORT = "rpt"
    EVENT = "evt"
    SYSTEM = "system"

@unique
class SysType(str, Enum):
    """SystemType for the shared bus"""
    APP_SHUTDOWN = "app_shutdown"
    UNIT_STOP = "unit_stop"
    UNIT_SHUTDOWN = "unit_shutdown"
    UNIT_HALTED = "unit_halted"
    UNIT_SLEEP = "unit_sleep"
    UNIT_WAKEUP = "unit_wakeup"
    ADDR_DEREGISTER  = "addr_deregister"
    EVT_ADDR_DEREGISTER = "evt_addr_deregister"
    BUS_IS_OVERCROWDED = "bus_is_overcrowded"
    # Subscribes
    SUB = "sub"
    UNSUB = "unsub"
    SUB_SETUP = "sub_setup"
    

@unique
class RptType(str, Enum):
    """ReportType for the shared bus"""
    DONE = "done"
    INTO_WORK = "into_work"
    TIME_EXTENSION_REQUEST = "time_extension_request"
    CANT_DO = "cant_do"
    NO_REGISTRED_EXECUTOR = "executor_missing"
    NO_SUBSCRIBED_EXECUTOR = "no_subscribed_executor"

@unique
class RptReason(str, Enum):
    """For CANT_DO and TIME_EXTENSION_REQUEST"""
    OK = "OK"
    # Rejection reasons (CANT_DO)
    MODULE_BUSY = "MODULE_BUSY"         # Single-threaded module is occupied
    INVALID_ARGS = "INVALID_ARGS"       # Command payload is corrupted or invalid
    RESOURCE_LOCKED = "RESOURCE_LOCKED" # Hardware or file is busy
    INTERNAL_ERROR = "INTERNAL_ERROR"   # Unhandled exception in module
    NOT_IMPLEMENTED = "not_implemented"

@unique
class ModuleType(str, Enum):
    UTILITY = "utility"   # Without loop, without Secretery:  mod+log
    SIGMA = "sigma"       # With loop, without Secretery:  mod_loop+log
    ZOMBIE = "zombie"     # Controlled by Secretery (via callbacks):  mod+secr_loop+log
    TICKABLE = "tickable" # Without loop, Secretery has loop, calls step():  mod_step+secr_loop+log
    MASTER = "master"     # Calls secr.step() from own loop:  mod_loop+secr+log


class SanapoError(Exception): pass
class ModuleAddressError(SanapoError): pass
class MessageInitError(SanapoError): pass