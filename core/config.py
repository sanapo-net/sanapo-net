# core/config.py
class Config():
    icmp_interval = 1000
    
    # For the kernel
    BUS_READ_LIMIT = 100
    CORE_TICK_RATE = 0.0025 # seconds

    # For buffer
    BUF_ICMP_SPARE_COLS_MAX = 150
    BUF_ICMP_SPARE_COLS_TARGET = 100
    BUF_ICMP_MIN_PER_SAMPLES_10M_DB = 40  # %
    BUF_ICMP_MIN_PER_SAMPLES_10M = 40     # %
    BUF_ICMP_MIN_PER_SAMPLES_3M = 70      # %
    BUF_ICMP_MIN_PER_SAMPLES_1M = 90      # %
    BUF_ICMP_MIN_PER_SAMPLES_DEFAULT = 90 # %

    # For scanner
    SCAN_ICMP_TIMEOUT_MARGIN = 0.1 # seconds

    # For the Secretary
    DEFAULT_CMD_DEADLINE_ANSW = 0.05    # seconds
    DEFAULT_CMD_DEADLINE_DONE = 0.8     # seconds
    DEFAULT_TIME_EXTENSION = 0.5        # seconds
    DEADLINE_EXTENSION_THRESHOLD = 0.3  # seconds
    SECRETARY_TICK_RATE_DEFAULT = 0.025 # seconds
    MODULE_TICK_SLA = {
        "KERNEL": 0.002,
        "BUFFER_ICMP": 0.0045,
    }
    # SLA Registry for specific commands (Contractual timeouts)
    CMD_SLA = {
        "CMD_TEST": 0.5,        # seconds
        "CMD_SCAN_NET": 30.0,   # seconds
    }

    def get_secretary_tick(self, addr_name: str) -> float:
        """
        Returns the specific tick rate for a module's secretary.
        Falls back to SECRETARY_TICK_RATE_DEFAULT if no custom SLA is defined.
        """
        return self.MODULE_TICK_SLA.get(addr_name, self.SECRETARY_TICK_RATE_DEFAULT)
    
    def get_deadline_dur(self, cmd_name: str) -> float:
        """
        Returns the execution deadline for a specific command name.
        Falls back to DEFAULT_CMD_DEADLINE_DONE if not in SLA.
        """
        return self.CMD_SLA.get(cmd_name, self.DEFAULT_CMD_DEADLINE_DONE)