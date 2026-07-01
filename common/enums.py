# common/enums.py
from enum import Enum

# --- Network ---

class Priority(str, Enum):
    HIGH  = "high"
    MEDIUM  = "medium"
    LOW = "low"


class DeviceType(str, Enum):
    UNKNOWN = "unknown"
    PC = "pc"
    LAPTOP = "LAPTOP"


class IfaceType(Enum):
    UNKNOWN = "unknown"
    # WiFi family
    WIFI_SOME = "wifi_some"
    WIFI_4 = "wifi_4"
    WIFI_5 = "wifi_5"
    WIFI_6 = "wifi_6"
    WIFI_6E = "wifi_6e"
    WIFI_7 = "wifi_7"
    # Copper family
    COPPER = "copper"
    # Fiber family
    FIBER_SINGLE = "fiber_single"
    FIBER_MULTI = "fiber_multi"
    
    @property
    def generation(self) -> int:
        """Returns the chronological weight of the standard for comparison."""
        weights = {
            IfaceType.WIFI_SOME: 0,
            IfaceType.WIFI_4: 4,
            IfaceType.WIFI_5: 5,
            IfaceType.WIFI_6: 6,
            IfaceType.WIFI_6E: 7,
            IfaceType.WIFI_7: 8
        }
        return weights.get(self, 0)

# --- ICMP Scan ---

class TickInterval(float, Enum):
    """Physical time constants in seconds."""
    OFF      = -100.0
    DEFAULT  = -1.0
    SEC_05   = 0.5
    SEC_1    = 1.0
    SEC_2    = 2.0
    SEC_4    = 4.0
    SEC_8    = 8.0
    SEC_24   = 24.0
    SEC_120  = 120.0


class SpeedShiftICMP(int, Enum):
    SLOWER = 1
    NORMAL = 0   
    FASTER = -1

# --- common ---

class EvtType(str, Enum):
    """EventType for the shared bus"""
    # --- cheked ---
    # Common
    EVT_TEST = "evt_test"

    # network
    NETWORK_NEW_VER = "network_new_ver"

    # icmp_scanner
    ICMP_NEW_INTERVALS = "icmp_new_intervals"

    # --- non cheked ---
    # Kernel
    TICK_05 = "tick_05"
    TICK_1 = "tick_1"
    TICK_2 = "tick_2"
    TICK_4 = "tick_4"
    TICK_8 = "tick_8"
    TICK_24 = "tick_24"
    TICK_120 = "tick_120"
    TICK_10M = "tick_10m" # every calendar 10min (system time)
    # ScanICMP
    ICMP_RAW_READY = "icmp_raw_ready"
    # BufferICMP
    ICMP_TICK_READY = "icmp_tick_ready"
    ICMP_AGR_WIN_1M_READY = "icmp_agr_win_1m_ready"
    ICMP_AGR_WIN_3M_READY = "icmp_agr_win_3m_ready"
    ICMP_AGR_WIN_10M_READY = "icmp_agr_win_10m_ready"
    ICMP_AGR_DB_10M_READY = "icmp_agr_db_10m_ready"
    ICMP_RAW_DB_10M_READY = "icmp_raw_db_10m_ready"
    ICMP_BUF_NEW_NET_VER_READY = "icmp_buf_new_net_ver_ready"
    ICMP_UIDS_BY_LATENCY_READY = "icmp_uids_by_latency_ready"


# for cheking and refactoring
class RollWin(int, Enum):
    MIN_1  = 60
    MIN_3  = 180 
    MIN_10 = 600

class CmdType(str, Enum):
    """CommandType for the shared bus"""
    APP_STOP = "app_stop"
    MODULE_STOP = "module_stop"
    CANCEL_TASK = "cancel_task" # TODO check: dont send answer INTO_WORK e.t.c.
    CMD_TEST = "cmd_test"
    # to ICMP buffer
    ICMP_BUF_AGR_WIN_REQ = "icmp_buf_agr_win_req"
    ICMP_BUF_AGR_DB_10M_REQ = "icmp_buf_agr_db_10m_req"
    ICMP_BUF_RAW_DB_10M_REQ = "icmp_buf_raw_db_10m_req"

class Metric(str, Enum):
    # Percentiles for distribution analysis
    P5      = "p5"
    P25     = "p25"
    P50     = "p50"   # Median
    P75     = "p75"
    P95     = "p95"
    # Basic statistical bounds
    MIN     = "min"
    MAX     = "max"
    AVG     = "avg"
    CV      = "cv"
    # Aggregated sums for secondary calculations (e.g., StdDev)
    SUM_RTT = "sum_rtt"
    SQ_SUM  = "sq_sum"  # Sum of squares
    # Counters and reliability metrics
    SAMPLE  = "sample" # int
    LOSS    = "loss"   # int
    STREAK  = "streak" # int
    # Network-specific jitter calculation
    JITTER  = "delta_jit"
