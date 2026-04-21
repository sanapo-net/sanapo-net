# core/config.py
from core.enums import CmdType, Addr, TickInterval, Logs

class Config():
    icmp_interval = 1000
    
    # Kernel
    BUS_READ_LIMIT = 100
    CORE_TICK_RATE = 0.0025 # seconds

    # BufferICMP
    BUF_ICMP_SPARE_COLS_MAX = 150
    BUF_ICMP_SPARE_COLS_TARGET = 100
    BUF_ICMP_MIN_PER_SAMPLES_10M_DB = 40  # %
    BUF_ICMP_MIN_PER_SAMPLES_10M = 40     # %
    BUF_ICMP_MIN_PER_SAMPLES_3M = 70      # %
    BUF_ICMP_MIN_PER_SAMPLES_1M = 90      # %
    BUF_ICMP_MIN_PER_SAMPLES_DEFAULT = 90 # %

    # Network
    NETWORK_TICK_SLA = 0.04 # seconds

    # ManagerICMP, ScannerISMP
    SCAN_ICMP_TIMEOUT_MIN_MARGIN = { # seconds
        TickInterval.SEC_05: 0.1,
        TickInterval.SEC_1: 0.1,
        TickInterval.SEC_2: 0.2,
        TickInterval.SEC_4: 0.4,
        TickInterval.SEC_8: 0.8,
        TickInterval.SEC_24: 3.2,
    }
    ICMP_SCAN_QUEUE_THRESHOLD = 50 # if SCAN_QUEUE > ICMP_SCAN_QUEUE_THRESHOLD drop corrent task
    ICMP_BATCH_SIZE_SMALL_NET = 15
    ICMP_NET_SIZE_THRESHOLD = 500
    ICMP_BATCH_CONFIG_LARGE = [
        (10, 80),  # Top 20% (highest priority) -> batch size 10
        (20, 50),  # Next 30% -> batch size 20
        (50, 0)    # Remaining 50% (background/slow) -> batch size 50
    ]
    ICMP_THREADS_MIN = 20
    ICMP_THREADS_MAX = 100
    ICMP_QUEUE_GROWTH_STEP = 15  # Queue threshold for pool scaling
    ICMP_TIMEOUTS = [-1, 25, 50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 1000,
                     1200, 1400, 1600, 1800, 2000, 3000, 4000, 5000, 6000, 7000]

    # Logger
    DEFAULT_LOG_FLAGS = {
        "console": [Logs.CRIT, Logs.ERR, Logs.WRN, Logs.INFO, Logs.DEBUG],
        "file": [Logs.CRIT, Logs.ERR, Logs.WRN, Logs.INFO, Logs.DEBUG],
        "message": [Logs.CRIT, Logs.ERR, Logs.WRN, Logs.INFO, Logs.DEBUG],
    }

    # Secretary
    DEFAULT_CMD_DEADLINE_ANSW = 0.05    # seconds
    DEFAULT_CMD_DEADLINE_DONE = 0.8     # seconds
    DEFAULT_TIME_EXTENSION = 0.5        # seconds
    DEADLINE_EXTENSION_THRESHOLD = 0.3  # seconds
    SECRETARY_TICK_RATE_DEFAULT = 0.025 # seconds
    MODULE_TICK_SLA = {
        "BUFFER_ICMP": 0.0045,
    }
    # SLA Registry for specific commands (Contractual timeouts)
    CMD_SLA: dict[CmdType, float] = {
        # in seconds
        CmdType.CMD_TEST: 0.3,
        CmdType.MODULE_STOP: 1,
    }

    def get_secretary_tick(self, addr: Addr) -> float:
        """
        Returns the specific tick rate for a module's secretary.
        Falls back to SECRETARY_TICK_RATE_DEFAULT if no custom SLA is defined.
        """
        return self.MODULE_TICK_SLA.get(addr, self.SECRETARY_TICK_RATE_DEFAULT)
    
    def get_deadline_dur(self, cmd_type: CmdType) -> float:
        """
        Returns the execution deadline for a specific command name.
        Falls back to DEFAULT_CMD_DEADLINE_DONE if not in SLA.
        """
        return self.CMD_SLA.get(cmd_type, self.DEFAULT_CMD_DEADLINE_DONE)
    
    MODULE_TICK_TCT_DEFAULT = 0.02 # Target Cycle Time, Seconds