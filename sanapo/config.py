# sanapo/config.py
from sanapo.enums import Logs, ShutdownTier

class Config():
    # Kernel
    THRESHOLD_BUS_OVERCROWDED = 100
    KERNEL_TICK_TCT = 0.0025 # seconds
    UNIT_SHUTDOWN_JOIN_INTERVAL = 0.3 # seconds
    UNIT_SHUTDOWN_JOIN_TIMEOUT = 0.02 # seconds
    UNIT_SHUTDOWN_TIMEOUT = { # seconds
        ShutdownTier.LOGIC: 0.5,
        ShutdownTier.DATA:  0.5,
        ShutdownTier.INFRA: 0.5,
    }

    # Logger
    PATH_LOGS = "/"
    DEFAULT_LOG_FLAGS = {
        "console": [Logs.CRT, Logs.ERR, Logs.WRN, Logs.INF, Logs.DBG],
        "file": [Logs.CRT, Logs.ERR, Logs.WRN, Logs.INF, Logs.DBG],
        "message": [Logs.CRT, Logs.ERR, Logs.WRN, Logs.INF, Logs.DBG],
    }

    # Secretary
    DEFAULT_CMD_DEADLINE_ANSW = 0.05    # seconds
    DEFAULT_CMD_DEADLINE_DONE = 0.8     # seconds
    DEFAULT_TIME_EXTENSION = 0.5        # seconds
    DEADLINE_EXTENSION_THRESHOLD = 0.3  # seconds
    SECRETARY_TICK_TCT_DEFAULT = 0.025  # seconds
    MODULE_TICK_TCT_DEFAULT = 0.02 # Target Cycle Time, Seconds

    # ThreadManager
    THREAD_TCT_DEFAULT = 0.02
    THREAD_TCT_HIBERNATE_DEFAULT = 0.1
    THREAD_JOIN_MARGIN = 2
    FPS_MODE = True
    HIBERNATE_MODE = True

    # BaseUnit
    UNIT_STOP_TIMEOUT = 2
