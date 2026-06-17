# sanapo/config.py
from sanapo.enums import Logs

class Config():
    # Kernel.
    KERNEL_TCT = 0.002 # seconds
    ADDR_KERNEL_STR = "KERNEL"
    ADDR_KERNEL = None
    SYS_CONSIST_DELAY = 5
    SYS_CONSIST_PATH = "sys_consists/"
    THRESHOLD_BUS_OVERCROWDED = 100
    FW_SUTDOWN_TIMEOUT = 5.000
    SYSTEM_STUCK_REBOOT_MAX = 1

    # Logger.
    PATH_LOGS = "logs/"
    DEFAULT_LOG_FLAGS = {
        "console": [Logs.CRT, Logs.ERR, Logs.WRN, Logs.INF, Logs.DBG],
        "file": []#[Logs.CRT, Logs.ERR, Logs.WRN, Logs.INF, Logs.DBG]
    }

    # TODO make another timings for net addrs
    # Secretary.
    DEFAULT_CMD_DEADLINE_ANSW = 0.150     # seconds
    DEFAULT_CMD_DEADLINE_DONE = 0.400     # seconds
    DEFAULT_TIME_EXTENSION = 0.200        # seconds
    DEADLINE_EXTENSION_THRESHOLD = 0.050  # seconds
    UNIT_BUS_READ_LIMIT = 20
    CMD_HISTORY_LIMIT = 100
    
    # ThreadManager.
    THREAD_TCT_DEFAULT = 0.005
    THREAD_TCT_HIBERNATE_DEFAULT = 0.050
    THREAD_STEP_TIMEOUT_DEFAULT = 0.100
    THREAD_JOIN_MARGIN = 1.000
    FPS_MODE = False
    HIBERNATE_MODE = True

    # BaseUnit.
    UNIT_START_TIMEOUT = 0.500
    UNIT_STOP_TIMEOUT = 2.000
    UNIT_STEP_TIMEOUT = 0.050

    # WatchDog.
    WATCHDOG_TCT = 1.000

    # Translator.
    TRANSLATOR_DIR = 'languarges/'
    UI_LANGUAGE = "en"

    # Transport.
    MAGIC_HEADER = b"SanaPo10"
    NET_PROJECT_TOKEN = b"PROJ00"
    TCP_PORT_DEFAULT = 50000
    UDP_PORT_DEFAULT = 50000
    HANDSHAKE_TIMEOUT = 5.000
    SYSTEM_NAME = 'SANAPO_FW'
    HOST = '0.0.0.0'
    NET_ALLOWED_IPS = ["127.0.0.1", "192.168.4.100", "192.168.4.101"]

    # Beacon
    NET_BEACON: bool = True                  # Enable beacon sending
    BEACON_SHORT_DURATION: float = 5.0       # Short interval duration
    BEACON_SHORT_INTERVAL: float = 5.0       # Short interval
    BEACON_LONG_INTERVAL: float = 30.0       # Long interval
    NET_AUTO_CONNECT_BY_BEACON: bool = True  # Auto-connect on beacon
    NET_PROJECT_MONO: bool = True            # Strict project token
    NET_MULTI_CONNECT_IN: bool = True
    NET_MULTI_CONNECT_OUT: bool = True
    CONN_WAIT_ANSW_MAX: float = 3.0

    # Keep-Alive
    CONN_KEEP_ALIVE: bool = True             # Keep connection alive
    CONN_KEEP_ALIVE_MAX: float = 30.0        # Idle time before ping

    # Security / Encryption
    NET_PASSWORD: str | bytes = None         # Password for XOR encryption
    NET_MAX_MSG_SIZE: int = 10 * 1024 * 1024 # Max message size (bytes)

    # Broker.
    ADDR_BROKER_STR = "BROKER"
    BROKER_BUS_READ_LIMIT = 500

    # BootMaster.
    BOOT_UI_MODE = "CUI" # "GUI" or "CUI"

