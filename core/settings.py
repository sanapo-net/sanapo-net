# core/settings.py
class Settings():
    icmp_interval = 1000
    # For the Bus
    BUS_READ_LIMIT = 200
    # For the Messenger
    DEFAULT_CMD_DEADLINE_ANSW = 0.05 # seconds
    DEFAULT_CMD_DEADLINE_DONE = 0.8 # seconds
    # For the Orchestrator
    TICK_RATE = 0.025 # seconds
    THREAD_POOL_MAX_SIZE = 20
