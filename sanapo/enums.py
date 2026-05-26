# sanapo/enums.py
from enum import Enum, IntEnum, unique
from dataclasses import dataclass
from typing import Type

from sanapo.addr import Addr

# Logger
@unique
class Logs(str, Enum):
    CRT = "crt"
    ERR = "err"
    WRN = "wrn"
    INF = "inf"
    DBG = "dbg"

# Tier
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

class TierTask(Enum):
    NONE = "none"
    STARTING = "starting"
    STOPPING = "stopping"

# BootMaster
class MasterMode(Enum):
    IDLE = "idle"
    BOOTING = "booting"
    SHUTDOWN = "shutdown"

# Protocol
@unique
class MsgType(str, Enum):
    CMD = "cmd"
    RPT = "rpt"
    EVT = "evt"
    SYS = "sys"

@unique
class SysType(str, Enum):
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
    RAW = "raw"
    NET_CONNECTED = "net_connected"
    NET_DISCONNECTED = "net_disconnected"
    REG_UNIT = "reg_unit"

@unique
class RptType(str, Enum):
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
class RptReason(str, Enum):
    """For CANT_DO and TIME_EXTENSION_REQUEST"""
    OK = "OK"
    # Rejection reasons (CANT_DO)
    MODULE_BUSY = "MODULE_BUSY"         # Single-threaded module is occupied
    INVALID_ARGS = "INVALID_ARGS"       # Command payload is corrupted or invalid
    RESOURCE_LOCKED = "RESOURCE_LOCKED" # Hardware or file is busy
    INTERNAL_ERROR = "INTERNAL_ERROR"   # Unhandled exception in module
    NOT_IMPLEMENTED = "not_implemented"

# Unit
@unique
class UnitType(str, Enum):
    UTILITY = "utility"   # Without loop, without Secretery:  mod + log
    SIGMA = "sigma"       # With loop, without Secretery:  mod_step + log
    ZOMBIE = "zombie"     # Controlled by Secretery (via callbacks):  mod + secr_step + log
    TICKABLE = "tickable" # Without loop, Secretery has loop, calls step():  mod_step + secr_step + log

@unique
class UnitStat(str, Enum):
    CREATING = "creating"
    CREATED = "created"
    STARTING = "starting"
    WORKING = "working"
    SLEEPING = "sleeping"
    STOPPING = "stopping"
    STOPPED = "stopped"
    HALTED = "halted"
    REBIRTHING = "rebirthing"
    DESTROYED = "destroyed"

# Thread
@unique
class ThreadType(Enum):
    TICKABLE = 0          # Active working thread
    EVENT_DRIVEN = 1      # Guest-friendly club (Zombie/Utility)
    ONLY_EVENT_DRIVEN = 2 # Strict VIP club (No Tickables allowed)

@unique
class ThreadStat(Enum):
    CREATED = "created"
    STARTING = "starting"
    WORKING = "working"
    RELOADING = "reloading"
    JOINING = "joining"
    JOINED = "joined"
    HALTED = "halted"

@unique
class UnitSource(Enum): # WHERE TO TAKE FROM (Source of objects)
    CURRENT = "current" # From active self._units dictionary
    INITIAL = "initial" # From the original config/startup list

@unique
class UnitSelection(Enum): # WHOM TO TAKE (Object state filter)
    ALL = "all"         # Select everything
    ALIVE = "alive"     # Only those whose thread is currently running
    DEAD = "dead"       # Only those finished or crashed (not alive)
    WORKING = "working" # Only those with 'WORKING' status

@unique
class ExecutionStrategy(Enum): # WHOM TO START (Post-creation action)
    NONE = "none"      # Create objects but do not call .start()
    ALL = "all"        # Start all selected units
    WORKING = "sync"   # Start only those that were running before the reload

# Translator
@unique
class TranspReadStat(Enum):
    OK = "ok"
    EMPTY = "empty"
    CORRUPTED = "corrupted"
    INCOMPLETE = "incomplete"
    AUTH_FAILED = "auth_failed"

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
    tier_stop: Type[ShutdownTier]

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
            tier_stop=ShutdownTier,
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