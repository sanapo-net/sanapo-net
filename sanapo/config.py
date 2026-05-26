# sanapo/config.py
from sanapo.enums import Logs

class Config():
    # Kernel.
    KERNEL_TCT = 0.0025 # seconds
    ADDR_KERNEL_STR = "KERNEL"
    ADDR_KERNEL = None
    SYS_CONSIST_DELAY = 5
    SYS_CONSIST_PATH = "sys_consists/"
    THRESHOLD_BUS_OVERCROWDED = 100

    # Logger.
    PATH_LOGS = "logs/"
    DEFAULT_LOG_FLAGS = {
        "console": [Logs.CRT, Logs.ERR, Logs.WRN, Logs.INF, Logs.DBG],
        "file": [Logs.CRT, Logs.ERR, Logs.WRN, Logs.INF, Logs.DBG],
        "message": [Logs.CRT, Logs.ERR, Logs.WRN, Logs.INF, Logs.DBG],
    }

    # Secretary.
    DEFAULT_CMD_DEADLINE_ANSW = 0.2    # seconds
    DEFAULT_CMD_DEADLINE_DONE = 0.8     # seconds
    DEFAULT_TIME_EXTENSION = 0.5        # seconds
    DEADLINE_EXTENSION_THRESHOLD = 0.3  # seconds
    UNIT_BUS_READ_LIMIT = 20

    # ThreadManager.
    THREAD_TCT_DEFAULT = 0.02
    THREAD_TCT_HIBERNATE_DEFAULT = 0.1
    THREAD_STEP_TIMEOUT_DEFAULT = 0.1
    THREAD_JOIN_MARGIN = 2
    FPS_MODE = False
    HIBERNATE_MODE = True

    # BaseUnit.
    UNIT_START_TIMEOUT = 0.5
    UNIT_STOP_TIMEOUT = 2
    UNIT_STEP_TIMEOUT = 0.2

    # WatchDog.
    WATCHDOG_TCT = 1

    # Translator.
    TRANSLATOR_DIR = 'languarges/'
    UI_LANGUAGE = "en"

    # Transport.
    MAGIC_HEADER = b"SanaPo10"
    TCP_PORT_DEFAULT = 5000
    UDP_PORT_DEFAULT = 5000
    HANDSHAKE_TIMEOUT = 5.0
    SYSTEM_NAME = 'SYSTEM_NAME'
    HOST = '0.0.0.0'
    UDP_BEACON_INTERVAL = 10.0
    CONN_KEEP_ALIVE = 30.0
    NET_AUTO_CONNECT = True
    NEEDS_NET_AUTO_CONNECT = True
    NET_STRICT_HANDSHAKE = True

    # Security V1
    NET_PROJECT_TOKEN = b"PROJ99" # secret marker
    NET_ALLOWED_IPS = ["127.0.0.1", "192.168.4.100", "192.168.4.101"] # white list. [] for all

    # Broker.
    ADDR_BROKER_STR = "BROKER"
    BROKER_BUS_READ_LIMIT = 500

    # BootMaster.
    BOOT_UI_MODE = "CUI" # "GUI" or "CUI"

