# sanapo/enums.py
from enum import Enum, unique, auto
from dataclasses import dataclass
from typing import Type

from sanapo.addr import Addr

class BriefEnumMixin:
    """Mixin for outputting text/value."""
    #def __repr__(self) -> str:
    #    return f"<{self.__class__.__name__}.{self.name}>"

    #def __str__(self) -> str:
    #    return f"{self.__class__.__name__}.{self.name}"
    pass

# Logger
@unique
class Logs(BriefEnumMixin, str, Enum):
    CRT = "crt"
    ERR = "err"
    WRN = "wrn"
    INF = "inf"
    DBG = "dbg"

# Tier
class TierStat(BriefEnumMixin, str, Enum):
    CREATED = "created"
    STARTING = "starting"
    WORKING = "working"
    STOPPING = "stopping"
    STOPPED = "stopped"

# BootMaster
class BootTask(BriefEnumMixin, str, Enum):
    NONE = "none"
    BOOT = "boot"
    SHUTDOWN = "shutdown"

# Protocol
@unique
class MsgType(BriefEnumMixin, str, Enum):
    CMD = "cmd"
    RPT = "rpt"
    EVT = "evt"
    SYS = "sys"

@unique
class SysType(BriefEnumMixin, str, Enum):
    """SystemType for the shared bus"""
    APP_SHUTDOWN = "app_shutdown"
    APP_RELOAD = "app_reload"
    ADDR_DEREGISTER  = "addr_deregister"
    BUS_IS_OVERCROWDED = "bus_is_overcrowded"
    # Subscribes
    SUB = "sub"
    UNSUB = "unsub"
    SUB_SETUP = "sub_setup"
    # Units
    U_START = "u_start"
    U_SLEEP = "u_sleep"
    U_WAKEUP = "u_wakeup"
    U_STOP = "u_stop"
    U_DESTROY = "u_destroy"
    U_STEP = "u_step"
    U_REBORN = "u_reborn"
    U_MUTATE = "u_mutate"
    # Transport
    RAW = "raw" # TODO ???
    NET_READY = "net_ready"
    NET_DISCONNECTED = "net_disconnected"

@unique
class RptType(BriefEnumMixin, str, Enum):
    """ReportType for the shared bus"""
    DONE = "done"
    INTO_WORK = "into_work"
    TIME_EXTENSION_REQUEST = "time_extension_request"
    CANT_DO = "cant_do"
    NO_REGISTRED_EXECUTOR = "executor_missing"
    NO_SUBSCRIBED_EXECUTOR = "no_subscribed_executor"
    REACTION_TIMEOUT = "reaction_timeout"
    EXECUTION_TIMEOUT = "execution_timeout"

@unique
class RptReason(BriefEnumMixin, str, Enum):
    """For CANT_DO and TIME_EXTENSION_REQUEST"""
    OK = "OK"
    # Rejection reasons (CANT_DO)
    MODULE_BUSY = "module_busy"         # Single-threaded module is occupied
    INVALID_ARGS = "invalid_args"       # Command payload is corrupted or invalid
    RESOURCE_LOCKED = "resource_locked" # Hardware or file is busy
    INTERNAL_ERROR = "internal_error"   # Unhandled exception in module
    NOT_IMPLEMENTED = "not_implemented"
    EXEC_EXCEPTION = "exec_exception"
    ANOTHER = "another"

# Unit
@unique
class UnitType(BriefEnumMixin, str, Enum):
    UTILITY = "utility"   # Without loop, without Secretery:  mod + log
    SIGMA = "sigma"       # With loop, without Secretery:  mod_step + log
    ZOMBIE = "zombie"     # Controlled by Secretery (via callbacks):  mod + secr_step + log
    TICKABLE = "tickable" # Without loop, Secretery has loop, calls step():  (mod + secr)_step + log

@unique
class UnitStat(BriefEnumMixin, str, Enum):
    CREATING = "creating"
    CREATED = "created"
    STARTING = "starting"
    WORKING = "working"
    SLEEPING = "sleeping"
    STOPPING = "stopping"
    STOPPED = "stopped"
    HALTED = "halted"
    REBIRTHING = "rebirthing"
    DESTROYING = "destroying"
    DESTROYED = "destroyed"

# Thread
@unique
class ThreadType(Enum):
    TICKABLE = 0          # Active working thread
    EVENT_DRIVEN = 1      # Guest-friendly club (Zombie/Utility)
    ONLY_EVENT_DRIVEN = 2 # Strict VIP club (No Tickables allowed)

@unique
class ThreadStat(BriefEnumMixin, str, Enum):
    CREATED = "created"
    STARTING = "starting"
    WORKING = "working"
    RELOADING = "reloading"
    JOINING = "joining"
    JOINED = "joined"
    HALTED = "halted"

@unique
class UnitSource(BriefEnumMixin, str, Enum): # WHERE TO TAKE FROM (Source of objects)
    CURRENT = "current" # From active self._units dictionary
    INITIAL = "initial" # From the original config/startup list

@unique
class UnitSelection(BriefEnumMixin, str, Enum): # WHOM TO TAKE (Object state filter)
    ALL = "all"         # Select everything
    ALIVE = "alive"     # Only those whose thread is currently running
    DEAD = "dead"       # Only those finished or crashed (not alive)
    WORKING = "working" # Only those with 'WORKING' status

@unique
class ExecutionStrategy(BriefEnumMixin, str, Enum): # WHOM TO START (Post-creation action)
    NONE = "none"      # Create objects but do not call .start()
    ALL = "all"        # Start all selected units
    WORKING = "working"# Start only those that were running before the reload

# Translator
@unique
class TranspReadStat(BriefEnumMixin, str, Enum):
    OK = "ok"
    EMPTY = "empty"
    CORRUPTED = "corrupted"
    INCOMPLETE = "incomplete"
    AUTH_FAILED = "auth_failed"

# TCP
@unique
class ConnState(Enum):
    IDLE = auto()
    SENT_CONN_REQ = auto()
    WAIT_TOKEN_RETURN = auto()
    WAIT_ACCEPT = auto()
    ACTIVE = auto()
    CLOSING = auto()
    CLOSED = auto()

# Register
@dataclass
class EnumRegistry:
    """Full Registry for framework and project-specific Enums."""
    # 1. For Frame
    addr: Type[Addr]
    msg: Type[MsgType]
    sys: Type[SysType]
    rpt: Type[RptType]
    reason: Type[RptReason]
    evt: Type[Enum] # from project
    cmd: Type[Enum] # from project

    # 2. Life loop
    u_type: Type[UnitType]
    u_stat: Type[UnitStat]
    t_type: Type[ThreadType]
    t_stat: Type[ThreadStat]

    # 3. Trasport and sourses
    source: Type[UnitSource]
    selection: Type[UnitSelection]
    transp_stat: Type[TranspReadStat]

    # 4. service
    logs: Type[Logs]

    @classmethod
    def create_default(cls, evt_cls: Type[Enum], cmd_cls: Type[Enum]) -> 'EnumRegistry':
        """Factory method to assemble a full registry using native framework enums."""
        return cls(
            addr=Addr,
            msg=MsgType,
            sys=SysType,
            rpt=RptType,
            reason=RptReason,
            evt=evt_cls,       # Project-specific enums
            cmd=cmd_cls,       # Project-specific enums
            u_type=UnitType,
            u_stat=UnitStat,
            t_type=ThreadType,
            t_stat=ThreadStat,
            source=UnitSource,
            selection=UnitSelection,
            transp_stat=TranspReadStat,
            logs=Logs
        )

# Register
@dataclass
class EnumRegistry:
    """Registry strictly for frame serialization and network protocol mapping."""
    # 1. Mandatory for Frame reconstruction
    addr: Type[Addr]
    msg: Type[MsgType]
    sys: Type[SysType]
    rpt: Type[RptType]
    reason: Type[RptReason]
    evt: Type[Enum] # from project-specific code
    cmd: Type[Enum] # from project-specific code

    @classmethod
    def create_default(cls, evt_cls: Type[Enum], cmd_cls: Type[Enum]) -> 'EnumRegistry':
        """Factory method to assemble a light protocol registry using native enums."""
        return cls(
            addr=Addr,
            msg=MsgType,
            sys=SysType,
            rpt=RptType,
            reason=RptReason,
            evt=evt_cls,
            cmd=cmd_cls
        )


class SanapoError(Exception): pass
class ModuleAddressError(SanapoError): pass
class MessageInitError(SanapoError): pass
class ClubAccessError(Exception): pass
class UnitMutationError(Exception): pass