# core/buffer_icmp.py
import threading
import numpy as np
from contextlib import contextmanager
from typing import Dict, List, Optional, Tuple, Any, Union
from core import enums
from core.protocol import Frame

class BufferICMP:
    """
    High-performance ICMP metrics buffer using circular NumPy matrices.
    Handles real-time ingestion, multi-tier aggregation, and thread-safe access.
    """
    
    SPARE_COLS_MAX = 150
    SPARE_COLS_TARGET = 100
    
    # 80% Quality Gate constants (Calculated for 8s max interval)
    # (Window_sec / 0.5s_tick) / (8s_max_interval / 0.5s_tick) * 0.8
    MIN_SAMPLES_3M = 18 
    MIN_SAMPLES_10M = 60

    def __init__(self, kernel, tools):
        self.kernel = kernel
        self.tools = tools  # Proxy to kernel.network and settings
        self.secr = None    # Secretary instance (to be set after init)
        
        # Concurrency primitives
        self._lock = threading.RLock()
        #self._cond_db = threading.Condition(self._lock) # For DB Manager synchronization
        
        # Topology state
        self.network_ver = -1
        self.uid_to_col: Dict[str, int] = {}
        self.free_slots: List[int] = []
        self.active_uids: List[str] = [] # The exact order for the Scanner
        
        # Time management
        self.head_idx = 0  # Points to the "NOW" row in the matrix (0-1199)
        
        # Main storage: 1200 rows (10 min history @ 0.5s ticks)
        # float16 is enough for RTT (ms) and supports NaN natively
        self._matrix = np.full((1200, self.SPARE_COLS_TARGET), np.nan, dtype=np.float16)

    # --- EXTERNAL ACCESS ---

    @contextmanager
    def get_icmp_view(self):
        """Thread-safe context manager for data readers."""
        with self._lock:
            # Returns references; the lock prevents Kernel from shifting/writing
            yield self._matrix, self.head_idx, self.active_uids

    # --- DATA INGESTION & TICKING ---

    def on_tick(self, frame: Optional[Frame] = None):
        """
        Master tick orchestrator (0.5s-8.0s). 
        
        Advances the circular buffer offset and executes pre-ingestion routines.
        Performing state updates prior to scanner data arrival,
        optimizes the critical path of the data pipeline and minimizes ingestion latency.
        """
        with self._lock:
            # Check if topology changed before we move forward
            if self.network_ver < self.tools.network_ver:
                self._sync_topology()
            
            # Advance head pointer (0 -> 1199 -> 0)
            self.head_idx = (self.head_idx + 1) % 1200
            
            # Wipe the new row to clear the oldest data (10min old)
            self._matrix[self.head_idx, :] = np.nan

            # If it's a 10-min calendar tick (TICK_600)
            if frame and frame.evt_type == enums.EvtType.TICK_600:
                # OPTION A: With Condition.wait (Notify DB Manager)
                #self._cond_db.notify_all()
                # OPTION B: Without wait (Just send event)
                self.secr.send_evt(enums.EvtType.ICMP_DB_DATA_READY)

    def scan_give_data(self, frame: Frame):
        """
        Ingest raw metrics from ICMP Scanner.
        Payload: {"net_ver": int, "data": list[float]}
        """
        p = frame.payload
        if p['net_ver'] < self.network_ver:
            return # Ignore outdated topology data

        with self._lock:
            # Map UIDs from scanner's order to matrix columns
            target_cols = [self.uid_to_col[uid] for uid in self.active_uids]
            
            try:
                # Fast vectorized assignment
                self._matrix[self.head_idx, target_cols] = p['data']
                self.secr.send_evt(enums.EvtType.ICMP_TICK_DATA_READY)
            except Exception as e:
                print(f"[BufferICMP] Ingest failed: {e}")

    # --- NET TOPOLOGY & MEMORY ---

    def _sync_topology(self):
        """Updates matrix schema and mapping based on NetworkTopology."""
        new_tab = self.tools.network_tab
        new_uids_set = set(new_tab.keys())
        curr_uids_set = set(self.uid_to_col.keys())

        # 1. Remove deleted: Wipe columns and free slots
        for uid in (curr_uids_set - new_uids_set):
            col = self.uid_to_col.pop(uid)
            self._matrix[:, col] = np.nan # clean slot
            self.free_slots.append(col)

        # 2. Add new: Find or create slots
        for uid in (new_uids_set - curr_uids_set):
            if not self.free_slots:
                self._expand_matrix()
            col = self.free_slots.pop()
            self.uid_to_col[uid] = col

        # 3. Finalize order
        self.active_uids = list(new_tab.keys())
        self.network_ver = self.tools.network_ver
        self._check_resizing()

    def _expand_matrix(self):
        """Extends matrix width by 100 columns."""
        ext = np.full((1200, 100), np.nan, dtype=np.float16)
        old_w = self._matrix.shape[1]
        self._matrix = np.hstack([self._matrix, ext])
        self.free_slots.extend(range(old_w + 99, old_w - 1, -1))

    def _check_resizing(self):
        """Shrinks matrix if free slots exceed SPARE_COLS_MAX."""
        # TODO: make it
        pass

    # --- AGGREGATION ---
    def get_window_metrics(self, seconds: int = 180) -> Dict[str, np.ndarray]:
        """
        Calculate metrics for rolling windows (1m, 3m, 10m).
        Distinguishes between Timeouts (-1) and No Data (NaN).
        """
        rows_needed = int(seconds / 0.5)
        
        # Dynamic quality gate (80% of expected samples)
        # TODO: Move to centralized settings/constants
        if seconds <= 60:
            min_samples = 96   # (60s / 0.5s) * 0.8
        elif seconds <= 180:
            min_samples = self.MIN_SAMPLES_3M
        else:
            min_samples = self.MIN_SAMPLES_10M

        with self._lock:
            # Shift circular buffer to linear: past at the top, present at the bottom
            data = np.roll(self._matrix, shift=-(self.head_idx + 1), axis=0)[-rows_needed:, :]
        
        # Masks for data filtering
        valid_mask = data >= 0   # Real RTT values (excludes NaN and -1)
        timeout_mask = data < 0  # Timeouts (-1)

        # Prepare data for math: replace timeouts and skips with NaN to ignore them
        calc_data = np.where(valid_mask, data, np.nan)

        with np.errstate(all='ignore'):
            # 1. Base counts
            sample_counts = np.sum(valid_mask | timeout_mask, axis=0)
            
            # 2. Vectorized Streak Calculation
            def _get_max_streak(m_2d):
                # Vertical stack a False row to handle edge cases at the start
                m = np.vstack([np.zeros(m_2d.shape[1], dtype=bool), m_2d])
                idx = np.where(~m, 0, 1)
                # Iterative prefix sum that resets on False (non-timeout) values
                for i in range(1, idx.shape[0]):
                    idx[i] *= (idx[i-1] + 1)
                return np.max(idx, axis=0)

            # 3. Jitter calculation (diff between adjacent successful RTTs)
            diffs = np.abs(np.diff(calc_data, axis=0))

            # 4. Primary Results Dictionary
            res = {
                "avg":          np.nanmean(calc_data, axis=0),
                "min":          np.nanmin(calc_data, axis=0),
                "max":          np.nanmax(calc_data, axis=0),
                "median":       np.nanmedian(calc_data, axis=0),
                "p95":          np.nanpercentile(calc_data, 95, axis=0),
                "loss_count":   np.sum(timeout_mask, axis=0).astype(np.int32),
                "loss_streak":  _get_max_streak(timeout_mask).astype(np.int32),
                "samples":      sample_counts.astype(np.int32),
                "delta_jitter": np.nanmean(diffs, axis=0)
            }
            
            # 5. Stability Monitoring (CV): deviation from avg in percent
            raw_cv = np.nanstd(calc_data, axis=0) / res["avg"]
            # Handle Zero RTT Anomaly (Critical Alert)
            inf_mask = np.isinf(raw_cv)
            if np.any(inf_mask):
                bad_indices = np.where(inf_mask)[0]
                bad_uids = [self.active_uids[i] for i in bad_indices]
                self.secr.send_evt(
                    enums.EvtType.MODULE_HEALTH_CRITICAL,
                    payload={
                        "reason": "ZERO_RTT_DETECTED",
                        "uids": bad_uids,
                        "msg": "Data corruption or scanner failure: RTT is zero."
                    }
                )
            # Clean up CV: replace Inf/NaN with proper NaN
            res["cv"] = np.where(np.isfinite(raw_cv), raw_cv, np.nan)

            # 6. Quality Gate: Nullify columns with insufficient data density
            quality_mask = sample_counts < min_samples
            for key in res:
                if isinstance(res[key], np.ndarray):
                    # Only apply to float arrays to preserve NaN support
                    if res[key].dtype.kind in 'fc':
                        res[key][quality_mask] = np.nan
                    
        return res

    def get_db_snapshot(self) -> Dict[str, np.ndarray]:
        """
        Aggregates full 10-minute matrix for SQL export.
        Includes Boxplot metrics (Q25, Q50, Q75) for historical reporting.
        """
        with self._lock:
            data = self._matrix.copy()
            
        # Masks for data filtering
        valid_mask = data >= 0   # Real RTT values
        timeout_mask = data < 0  # Timeouts (-1)
        
        # Data preparation (Ignore -1 and NaN for mathematical stats)
        calc_data = np.where(valid_mask, data, np.nan)

        with np.errstate(all='ignore'):
            return {
                "sent":    np.sum(valid_mask | timeout_mask, axis=0, dtype=np.int32),
                "lost":    np.sum(timeout_mask, axis=0, dtype=np.int32),
                "sum_rtt": np.nansum(calc_data, axis=0),
                "sq_sum":  np.nansum(np.square(calc_data), axis=0),
                "min":     np.nanmin(calc_data, axis=0),
                "max":     np.nanmax(calc_data, axis=0),
                # --- Boxplot metrics ---
                "p5":     np.nanpercentile(calc_data, 5, axis=0),
                "q25":     np.nanpercentile(calc_data, 25, axis=0),
                "q50":     np.nanmedian(calc_data, axis=0), # Equal to Q50
                "q75":     np.nanpercentile(calc_data, 75, axis=0),
                "p95":     np.nanpercentile(calc_data, 95, axis=0)
            }


    # --- OPTION A: WAIT INTERFACE FOR DB MANAGER ---
    
    def wait_for_db_cycle(self, timeout: float = 615.0):
        """
        Blocks the calling thread until the 10-minute aggregation is ready.
        Must be called from a dedicated DB Manager thread.
        """
        with self._lock:
            # Returns True if notified, False if timed out
            return self._cond_db.wait(timeout=timeout)
