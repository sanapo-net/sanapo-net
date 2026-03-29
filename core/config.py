# core/config.py
class Config():
    icmp_interval = 1000
    # For the kernel
    BUS_READ_LIMIT = 100
    CORE_TICK_RATE = 0.0025 # seconds
    # For the Secretary
    DEFAULT_CMD_DEADLINE_ANSW = 0.05 # seconds
    DEFAULT_CMD_DEADLINE_DONE = 0.8 # seconds
    DEFAULT_TIME_EXTENSION = 0.5 # seconds
    DEADLINE_EXTENSION_THRESHOLD = 0.3 # seconds
    SECRETARY_TICK_RATE = 0.025 # seconds

