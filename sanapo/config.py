# sanapo/config.py
from sanapo.enums import Logs

class Config():
    # Kernel.
    THRESHOLD_BUS_OVERCROWDED = 100
    KERNEL_TICK_TCT = 0.0025 # seconds
    UNIT_SHUTDOWN_JOIN_INTERVAL = 0.3 # seconds
    UNIT_SHUTDOWN_JOIN_TIMEOUT = 0.02 # seconds

    # Logger.
    PATH_LOGS = "logs/"
    DEFAULT_LOG_FLAGS = {
        "console": [Logs.CRT, Logs.ERR, Logs.WRN, Logs.INF, Logs.DBG],
        "file": [Logs.CRT, Logs.ERR, Logs.WRN, Logs.INF, Logs.DBG],
        "message": [Logs.CRT, Logs.ERR, Logs.WRN, Logs.INF, Logs.DBG],
    }

    # Secretary.
    DEFAULT_CMD_DEADLINE_ANSW = 0.05    # seconds
    DEFAULT_CMD_DEADLINE_DONE = 0.8     # seconds
    DEFAULT_TIME_EXTENSION = 0.5        # seconds
    DEADLINE_EXTENSION_THRESHOLD = 0.3  # seconds
    UNIT_BUS_READ_LIMIT = 20

    # ThreadManager.
    THREAD_TCT_DEFAULT = 0.02
    THREAD_TCT_HIBERNATE_DEFAULT = 0.1
    THREAD_STEP_TIMEOUT_MARGIN = 1
    THREAD_JOIN_MARGIN = 2
    FPS_MODE = True
    HIBERNATE_MODE = True

    # BaseUnit.
    UNIT_START_TIMEOUT = 0.5
    UNIT_STOP_TIMEOUT = 2
    UNIT_STEP_TIMEOUT = 0.2

    # WatchDog.
    WATCHDOG_TCT = 1
