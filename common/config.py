# common/config.py
from __future__ import annotations
from common.enums import TickInterval

class Config:
    """For parameters that can be changed during program debugging"""

    # Fixed number of worker threads in the ICMP pool
    ICMP_SCAN_THREADS_AMOUNT: int = 100

    # Maximum queue task threshold
    ICMP_SCAN_QUEUE_THRESHOLD_MAX: int = 150
    ICMP_SCAN_QUEUE_THRESHOLD: int = 50

    # Maximum size of a single host batch
    ICMP_BATCH_SIZE_MAX: int = 50
    ICMP_BATCH_SIZE_SMALL_NET: int = 15
    ICMP_NET_SIZE_THRESHOLD: int = 500
    ICMP_BATCH_CONFIG_LARGE: list[tuple[int, int]] = [
        (10, 80),   # Top 20% -> batch size 10
        (20, 50),   # Next 30% -> batch size 20
        (50, 0)     # Remaining 50% -> batch size 50
    ]

    # Allowed ICMP timeouts (ms)
    ICMP_TIMEOUTS: list[int] = [
        -1, 25, 50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 1000,
        1200, 1400, 1600, 1800, 2000, 3000, 4000, 5000, 6000, 7000
    ]

    # Minimum time margins for timeouts (sec)
    SCAN_ICMP_TIMEOUT_MIN_MARGIN: dict[TickInterval, float] = {
        TickInterval.SEC_05: 0.1,
        TickInterval.SEC_1:  0.1,
        TickInterval.SEC_2:  0.2,
        TickInterval.SEC_4:  0.4,
        TickInterval.SEC_8:  0.8,
        TickInterval.SEC_24: 3.2,
    }

    # --- Scheduler parameters (previously implicit in ManagerICMP) ---
    # Minimum batch size for different intervals
    CATEGORY_MIN_BATCH: dict[TickInterval, int] = {
        TickInterval.SEC_05: 2,
        TickInterval.SEC_1:  4,
        TickInterval.SEC_2:  6,
        TickInterval.SEC_4:  8,
        TickInterval.SEC_8:  10,
    }

    # Base worker distribution (for proportional calculation)
    BASE_WORKERS_PER_CATEGORY: dict[TickInterval, int] = {
        TickInterval.SEC_05: 60,
        TickInterval.SEC_1:  40,
        TickInterval.SEC_2:  25,
        TickInterval.SEC_4:  15,
        TickInterval.SEC_8:  10,
    }

    # Maximum batch size per interval
    ICMP_MAX_BATCH_PER_CATEGORY: dict[TickInterval, int] = {
        TickInterval.SEC_05: 30,
        TickInterval.SEC_1:  50,
        TickInterval.SEC_2:  80,
        TickInterval.SEC_4:  120,
        TickInterval.SEC_8:  200,
    }

    # Extra time added to task timeout for TTL calculation (sec)
    SCAN_ICMP_TTL_EXTRA: float = 0.05   # 50 ms

    # Default TTL (if unable to calculate)
    SCAN_ICMP_DEFAULT_TTL: float = 5.0


# for refactoring
class OLD_Config():
    # BufferICMP
    BUF_ICMP_SPARE_COLS_MAX = 150
    BUF_ICMP_SPARE_COLS_TARGET = 100
    BUF_ICMP_MIN_PER_SAMPLES_10M_DB = 40  # %
    BUF_ICMP_MIN_PER_SAMPLES_10M = 40     # %
    BUF_ICMP_MIN_PER_SAMPLES_3M = 70      # %
    BUF_ICMP_MIN_PER_SAMPLES_1M = 90      # %
    BUF_ICMP_MIN_PER_SAMPLES_DEFAULT = 90 # %
    # ScanICMP
    ICMP_SCAN_QUEUE_THRESHOLD = 50 # if SCAN_QUEUE > ICMP_SCAN_QUEUE_THRESHOLD drop corrent task
    ICMP_BATCH_SIZE_SMALL_NET = 15
    ICMP_NET_SIZE_THRESHOLD = 500
