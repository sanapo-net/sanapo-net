# core/buffer_icmp.py
import threading
import numpy as np
import time
from contextlib import contextmanager
from typing import Dict, List, Optional, Any

from core.enums import EvtType, RollWin
from core.protocol import Frame

class BufferICMP:
    """
    High-performance ICMP metrics buffer using circular NumPy matrices.
    Handles real-time ingestion, multi-tier aggregation, and thread-safe access.
    """

    def __init__(self, tools, secr):
        self._secr = secr
        self._tools = tools
        
        self._spare_max = tools.config.BUF_ICMP_SPARE_COLS_MAX
        self._spare_target = tools.config.BUF_ICMP_SPARE_COLS_TARGET
        
        # Validate configuration consistency
        if self._spare_max <= self._spare_target:
            err = f"Config Error: MAX ({self._spare_max}) <= TARGET ({self._spare_target})"
            raise RuntimeError(err)

        self._lock = threading.RLock()
        
        # agredated data by last and prev time 1/3/10 minute window
        self._agr_win = {
            RollWin.MIN_1: [None, None],
            RollWin.MIN_3: [None, None],
            RollWin.MIN_10:[None, None]
        }
        # agredated data by last "calendar" 10 minute
        self._agr_db = None # {'start_time': start_time, 'res': res}
        # raw data by last "calendar" 10 minute
        self._raw_db = None 

        self._tick_id = -1

        self._network_ver = -1
        self._active_uids: List[str] = [] # holds active interfaces' uids
        self._free_slots: List[int] = [] # holds id of free cols into matrix
        self._uid_to_col: Dict[str, int] = {} # {uid:id_of_col_in_to_matrix, ...}
        
        self._head_idx = 0 
        
        self._matrix = np.full((1200, self._spare_target), np.nan, dtype=np.float16)
        self._free_slots = list(range(self._spare_target - 1, -1, -1))

        self._secr.start()
        self._secr.sconfigure_subscriptions(
            events = {
                EvtType.TICK_05: self._every_tick,
                EvtType.TICK_1: self._every_tick,
                EvtType.TICK_2: self._every_tick,
                EvtType.TICK_4: self._every_tick,
                EvtType.TICK_8: self._every_tick,
                EvtType.TICK_24: self._every_tick,
                EvtType.TICK_120: self._every_tick,
                EvtType.TICK_10M: self._tick_10m,
                EvtType.NETWORK_NEW_VER: self._sync_topology,
                EvtType.ICMP_RAW_READY: self._scan_give_data,
            }
        )

    @property
    def network_ver(self) -> int: return self._network_ver
    
    @property
    def uid_to_col(self) -> Dict[str, int]: return self._uid_to_col

    @property
    def agr_win(self) -> Dict[RollWin, list[Dict, Dict]]: return self._agr_win
    
    @property
    def agr_db(self) -> Dict: return self._agr_db
    
    @property
    def raw_db(self) -> Dict: return self._raw_db

    # --- TICKING & DATA INGESTION---

    def _every_tick(self, frame: Optional[Frame] = None):
        """
        Advances the circular buffer offset and executes pre-ingestion routines.
        Performing state updates prior to scanner data arrival,
        optimizes the critical path of the data pipeline and minimizes ingestion latency.
        """
        with self._lock:
            if self._network_ver < self._tools.network_ver:
                self._sync_topology()
            # Advance head pointer (0 -> 1199 -> 0)
            self._head_idx = (self._head_idx + 1) % 1200
            # Wipe the new row to clear the oldest data (10min old)
            self._matrix[self._head_idx, :] = np.nan
            self._tick_id = frame.payload['tick_id']

    def _tick_10m(self, frame: Optional[Frame] = None):
        self._calc_db_snapshot()
        self._calc_db_snapshot()

    def _scan_give_data(self, frame: Frame):
        """
        Ingest raw metrics from ICMP Scanner.
        Payload: {"net_ver": int, "data": list[float]}
        """
        p = frame.payload
        if p['net_ver'] < self._network_ver:
            return # Ignore outdated topology data
        if p['tick_id'] < self._tick_id:
            return # Ignore outdated tick data

        with self._lock:
            # Map UIDs from scanner's order to matrix columns
            target_cols = [self._uid_to_col[uid] for uid in self._active_uids]
            try:
                # Fast vectorized assignment
                self._matrix[self._head_idx, target_cols] = p['data']
                self._secr.send_evt(
                    EvtType.ICMP_TICK_READY,
                    payload={
                        'net_ver': self._network_ver,
                        'tick_id': self._tick_id,
                        'data': p['data']
                        }
                )
            except Exception as e:
                print(f"[BufferICMP] Ingest failed: {e}")
            if frame.payload['tick_type'] == EvtType.TICK_8:
                self._calc_window_metrics(RollWin.MIN_1)
            elif frame.payload['tick_type'] == EvtType.TICK_24:
                self._calc_window_metrics(RollWin.MIN_3)
            elif frame.payload['tick_type'] == EvtType.TICK_120:
                self._calc_window_metrics(RollWin.MIN_10)


    # --- NET TOPOLOGY & MEMORY ---

    def _sync_topology(self):
        """Updates matrix schema and mapping based on NetworkTopology."""
        with self._lock:
            new_tab = self._tools.network_tab
            new_uids_set = set(new_tab.keys())
            curr_uids_set = set(self._uid_to_col.keys())

            # 1. Remove deleted: Wipe columns and free slots
            for uid in (curr_uids_set - new_uids_set):
                col = self._uid_to_col.pop(uid)
                self._matrix[:, col] = np.nan # clean slot
                self._free_slots.append(col)

            # 2. Add new uids: Find free slots or create new slots
            for uid in (new_uids_set - curr_uids_set):
                if not self._free_slots:
                    self._expand_matrix()
                col = self._free_slots.pop()
                self._uid_to_col[uid] = col

            # 3. Finalize order
            self._active_uids = list(new_tab.keys())
            self._network_ver = self._tools.network_ver
            if len(self._free_slots) > self._tools.config.BUF_ICMP_SPARE_COLS_MAX:
                self._compact_matrix()

    def _expand_matrix(self):
        """Extends matrix width by 100 columns."""
        with self._lock:
            ext = np.full((1200, 100), np.nan, dtype=np.float16)
            old_w = self._matrix.shape[1]
            self._matrix = np.hstack([self._matrix, ext])
            self._free_slots.extend(range(old_w + 99, old_w - 1, -1))

    def _compact_matrix(self):
        """Smart partial compaction of the matrix to optimize memory usage."""
        # Fast check without lock for better performance
        if len(self._free_slots) <= self._spare_max:
            return
        
        with self._lock:
            # Memory Integrity Guard (Internal Invariant Check)
            free_w = len(self._free_slots)
            occupied_w = len(self._uid_to_col)
            actual_w = self._matrix.shape[1]
            target_w = occupied_w + self._spare_target
            
            if actual_w != (occupied_w + free_w):
                # Critical bug: data/index mismatch. Reporting and aborting.
                msg = f"Memory Invariant Violation! {actual_w} != {occupied_w} + {free_w}"
                self._report_logic_err(msg)
                return
            
            # Check if shrinking is physically necessary
            if actual_w <= target_w:
                return

            # Evacuation: Identify active UIDs located in the 'Tail Zone'
            uids_to_move = [uid for uid, col in self._uid_to_col.items() if col >= target_w]

            if uids_to_move:
                # Find available slots within the 'Safe Zone' (0 to target_w)
                safe_slots = [s for s in self._free_slots if s < target_w]
                
                for uid in uids_to_move:
                    if not safe_slots:
                        # Resource saturation: no room to evacuate. Postponing.
                        self._report_logic_err("Evacuation failed: No safe slots!")
                        return 
                    
                    old_col = self._uid_to_col[uid]
                    new_col = safe_slots.pop(0)
                    
                    # Physical data relocation (Column copy)
                    self._matrix[:, new_col] = self._matrix[:, old_col]
                    self._uid_to_col[uid] = new_col

                    print(f"[BufferICMP] Evacuated {uid} from col {old_col} to {new_col}")

            # Physical Truncation
            self._matrix = self._matrix[:, :target_w]
            
            # Index Reconciliation
            self._free_slots = [s for s in self._free_slots if s < target_w]
            
            print(f"[BufferICMP] Compaction success: {actual_w} -> {target_w}")


    # --- AGGREGATION ---

    # TODO Optimize: Combine 10m window aggregation and 10m calendar aggregation for the DB
    
    def _calc_window_metrics(self, window: RollWin) -> Dict[str, np.ndarray]:
        """
        Calculate metrics for rolling windows (1m, 3m, 10m).
        Distinguishes between Timeouts (-1) and No Data (NaN).
        """
        rows_needed = int(window / 0.5)
        threshold_map = {
            RollWin.MIN_1:  self._tools.settings.BUF_ICMP_MIN_PER_SAMPLES_1M,
            RollWin.MIN_3:  self._tools.settings.BUF_ICMP_MIN_PER_SAMPLES_3M,
            RollWin.MIN_10: self._tools.settings.BUF_ICMP_MIN_PER_SAMPLES_10M
        }
        min_pct = threshold_map.get(window, self._tools.settings.BUF_ICMP_MIN_PER_SAMPLES_DEFAULT)
        min_samples = int(rows_needed * (min_pct / 100))

        with self._lock:
            # Shift circular buffer to linear: past at the top, present at the bottom
            data = np.roll(self._matrix, shift=-(self._head_idx + 1), axis=0)[-rows_needed:, :]
        
        # Masks for data filtering
        valid_mask = data >= 0   # Real RTT values (excludes NaN and -1)
        timeout_mask = data < 0  # Timeouts (-1)

        # Prepare data for math: replace timeouts and skips with NaN to ignore them
        calc_data = np.where(valid_mask, data, np.nan)

        with np.errstate(all='ignore'):
            sample_counts = np.sum(valid_mask | timeout_mask, axis=0)
            diffs = np.abs(np.diff(calc_data, axis=0)) # Jitter calculation
            perc_values = np.nanpercentile(calc_data, [5, 25, 50, 75, 95], axis=0)

            res = {
                "p5":           perc_values[0],
                "p25":          perc_values[1],
                "p50":          perc_values[2],
                "p75":          perc_values[3],
                "p95":          perc_values[4],
                "min":          np.nanmin(calc_data, axis=0),
                "max":          np.nanmax(calc_data, axis=0),
                "sum_rtt":      np.nansum(calc_data, axis=0),
                "sq_sum":       np.nansum(np.square(calc_data), axis=0),
                "sample":       sample_counts.astype(np.int32),
                "loss_count":   np.sum(timeout_mask, axis=0, dtype=np.int32),
                "loss_streak":  self._get_max_streak(timeout_mask).astype(np.int32),
                "delta_jitter": np.nanmean(diffs, axis=0),
                "avg":          np.nanmean(calc_data, axis=0),
            }
            
            # Stability Monitoring (Coefficient of Variation, deviation from avg in percent)
            raw_cv = np.nanstd(calc_data, axis=0) / res["avg"]
            
            # Zero RTT Anomaly checking
            inf_mask = np.isinf(raw_cv)
            if np.any(inf_mask):
                bad_uids = [self._active_uids[i] for i in np.where(inf_mask)[0]]
                msg = f"Data corruption or scanner failure: RTT is zero. bad_uids: {bad_uids}"
                self._report_logic_err(msg)

            # Clean up CV: replace Inf/NaN with proper NaN
            res["cv"] = np.where(np.isfinite(raw_cv), raw_cv, np.nan)

            # Quality Gate: if sample_counts < min_samples -> NaN
            quality_mask = sample_counts < min_samples
            for key in res:
                if isinstance(res[key], np.ndarray):
                    # Only apply to float arrays to preserve NaN support
                    if res[key].dtype.kind in 'fc':
                        res[key][quality_mask] = np.nan

        # Save res
        self._agr_win[window].insert(0, {
            'tick_id': self._tick_id,
            'net_ver': self._network_ver,
            'res':     res
        })
        self._agr_win[window].pop()

    def _calc_db_snapshot(self) -> Dict[str, np.ndarray]:
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

        # Returns a 2D array [5, N_devices]
        perc_values = np.nanpercentile(calc_data, [5, 25, 50, 75, 95], axis=0)
        
        # Time of starting this 10-minute time-pie
        start_time = (time.time() // 600) * 600
        
        with np.errstate(all='ignore'):
            res = {
                "p5":        perc_values[0],
                "p25":       perc_values[1],
                "p50":       perc_values[2],
                "p75":       perc_values[3],
                "p95":       perc_values[4],
                "min":       np.nanmin(calc_data, axis=0),
                "max":       np.nanmax(calc_data, axis=0),
                "sum_rtt":   np.nansum(calc_data, axis=0),
                "sq_sum":    np.nansum(np.square(calc_data), axis=0),
                "sample":    np.sum(valid_mask | timeout_mask, axis=0, dtype=np.int32),
                "loss_count":np.sum(timeout_mask, axis=0, dtype=np.int32),
            }
            self._agr_db = {'start_time': start_time, 'res': res}
        
    def _calc_raw_staging_data(self) -> Dict[str, Any]:
        """
        Prepares a 10-minute raw data package for the DB Staging Area.
        Returns a dict with binary matrix, UID mapping, and start timestamp.
        """
        with self._lock:
            # Reorder so the oldest row is first, newest is last
            linear_matrix = np.roll(self._matrix, shift=-(self._head_idx + 1), axis=0)
            # Time of starting this 10-minute time-pie
            start_time = (time.time() // 600) * 600
            
            self._raw_db = {
                "start_time": start_time,
                "net_ver":    self._network_ver,
                "uids":       list(self._active_uids),
                "blob":       linear_matrix.tobytes() 
            }


    # --- OTHER ---
        
    def _report_logic_err(self, msg: str):
        """Sends a critical logic error event to the shared bus for alerting."""
        print(f"[BUFFER_LOGIC_ERR] {msg}")
        if self._secr:
            self._secr.send_evt(
                EvtType.ERR_LOGIC,
                payload={"text": msg}
            )

    def _get_max_streak(m_2d):
        # Used into _calc_*(). Vertical stack a False row to handle edge cases at the start
        m = np.vstack([np.zeros(m_2d.shape[1], dtype=bool), m_2d])
        idx = np.where(~m, 0, 1)
        # Iterative prefix sum that resets on False (non-timeout) values
        for i in range(1, idx.shape[0]):
            idx[i] *= (idx[i-1] + 1)
        return np.max(idx, axis=0)
    
    # --- Drafts. TODO use or del ---

    # Returns True if notified, False if timed out
    @contextmanager
    def _get_icmp_view(self):
        """Thread-safe context manager for data readers."""
        with self._lock:
            # Returns references; the lock prevents Kernel from shifting/writing
            yield self._matrix, self._head_idx, self._active_uids

    def _wait_for_db_cycle(self, timeout: Optional[float] = None):
        """
        Blocks the calling thread until the 10-minute aggregation is ready.
        Must be called from a dedicated DB Manager thread.
        """
        if timeout is None:
            timeout = 600 * 1.2
        with self._lock:
            # Returns True if notified, False if timed out
            return self._cond_db.wait(timeout=timeout)
