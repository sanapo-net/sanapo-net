# core/buffer_icmp.py
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from main import Tools
    from core.network.network_manager import NetworkSnapshot
    from core.secretary import Secretary
    from numpy.typing import NDArray
    from core.protocol import Frame

import numpy as np
from threading import RLock

from core.enums import EvtType, CmdType, RptType, RollWin, SanapoError

class BufferICMP:
    """
    High-performance ICMP metrics buffer using circular NumPy matrices.
    Handles real-time ingestion, multi-tier aggregation, and thread-safe access.
    """
    def __init__(self, tools: Tools, secr: Secretary) -> None:
        self._secr: Secretary = secr
        self._tools: Tools = tools
        
        self._lock = RLock()
        
        self._tick_id: int = -1
        self._net_snapshot: NetworkSnapshot = None
        
        self._spare_max: int = tools.config.BUF_ICMP_SPARE_COLS_MAX
        self._spare_target: int = tools.config.BUF_ICMP_SPARE_COLS_TARGET
        # Validate configuration consistency
        if self._spare_max <= self._spare_target:
            err = f"Config Error: MAX ({self._spare_max}) <= TARGET ({self._spare_target})"
            raise SanapoError(err)
        
        # agredated data by last "calendar" 10 minute
        self._agr_db: dict[str, any] = None # {'start_time': start_time, 'res': res}
        # raw data by last "calendar" 10 minute
        self._raw_db: dict[str, any] = None
        # agredated data by last and prev time 1/3/10 minute window
        self._agr_win = dict[RollWin, list[dict[str, any]]] = {
            RollWin.MIN_1: [{}, {}],
            RollWin.MIN_3: [{}, {}],
            RollWin.MIN_10:[{}, {}]
        }

        self._active_uids: list[str] = [] # holds active interfaces' uids
        self._free_slots: list[int] = list(range(self._spare_target - 1, -1, -1))
        self._uid_to_col: dict[str, int] = {} # {uid:id_of_col_in_to_matrix, ...}
        
        self._head_idx: int = 0
        self._matrix = np.full((1200, self._spare_target), np.nan, dtype=np.float16)

        self._secr.start()
        self._secr.configure_subscriptions(
            events={
                EvtType.TICK_05: self._on_tick,
                EvtType.TICK_1: self._on_tick,
                EvtType.TICK_2: self._on_tick,
                EvtType.TICK_4: self._on_tick,
                EvtType.TICK_8: self._on_tick,
                EvtType.TICK_24: self._on_tick,
                EvtType.TICK_120: self._on_tick,
                EvtType.TICK_10M: self._tick_10m,
                EvtType.NETWORK_NEW_VER: self._sync_topology,
                EvtType.ICMP_RAW_READY: self._scan_give_data,
            },
            commands={
                CmdType.ICMP_BUF_AGR_WIN_REQ: self._on_agr_win_req,
                CmdType.ICMP_BUF_AGR_DB_10M_REQ: self._on_agr_db_10m_req,
                CmdType.ICMP_BUF_RAW_DB_10M_REQ: self._on_raw_db_10m_req,
            }
        )

    # --- REPORTS ---

    def _on_agr_win_req(self, cmd: Frame) -> None:
        win = cmd.payload.get("RollWin", False)
        if win:
            payload = {win.name:[self._agr_win[win][0], self._agr_win[win][1]]}
        else:
            payload = {key.name:[val[0], val[1]] for key, val in self._agr_win.items()}
        self._secr.send_rpt(cmd.sender, cmd.cmd_id, RptType.DONE, payload)

    def _on_agr_db_10m_req(self, cmd: Frame) -> None:
        self._secr.send_rpt(cmd.sender, cmd.cmd_id, RptType.DONE, self._agr_db)

    def _on_raw_db_10m_req(self, cmd: Frame) -> None:
        self._secr.send_rpt(cmd.sender, cmd.cmd_id, RptType.DONE, self._raw_db)


    # --- TICKING & DATA INGESTION ---

    def _tick_10m(self, evt: Frame) -> None:
        """Prepares data objects for the last 10 calendar minutes in raw and aggregated."""
        time = evt.payload["time"]
        self._agr_db = self._get_agr_db_10m_data(time)
        self._raw_db = self._get_raw_db_10m_data(time)
        self._uids_by_latency = self._get_uids_by_latency(time)
        self._secr.send_evt(EvtType.ICMP_AGR_DB_10M_READY, {"data": self._agr_db})
        self._secr.send_evt(EvtType.ICMP_RAW_DB_10M_READY, {"data": self._raw_db})
        paload = {"uids_by_latency": self._uids_by_latency}
        self._secr.send_evt(EvtType.ICMP_UIDS_BY_LATENCY_READY, paload)

    def _on_tick(self, evt: Frame) -> None:
        """Advances the circular buffer offset and executes pre-ingestion routines."""
        with self._lock:
            # Advance head pointer (0 -> 1199 -> 0)
            self._head_idx = (self._head_idx + 1) % 1200
            # Wipe the new row to clear the oldest data (10min old)
            self._matrix[self._head_idx, :] = np.nan
            self._tick_id = evt.payload['tick_id']

    def _scan_give_data(self, evt: Frame) -> None:
        """
        Ingest raw metrics from ICMP Scanner.
        Writes data from the scanner to the matrix.
        If the time for sliding window aggregation has arrived,
        it aggregates and emits an event with the aggregated data.
        """
        payload_i = evt.payload
        # Frame with outdated topology data
        if payload_i['snapshot'].version != self._net_snapshot.version:
            text = "icmp_scanner provided icmp_buffer with stale snapshot data"
            self._secr.send_evt(EvtType.LOG, {"text":text})
            return
        # Frame with outdated tick data
        if payload_i['tick_id'] != self._tick_id:
            text = "icmp_scanner provided icmp_buffer with stale tick_id data"
            self._secr.send_evt(EvtType.LOG, {"text":text})
            return
        # Frame with current data
        with self._lock:
            # Map UIDs from scanner's order to matrix columns
            target_cols = [self._uid_to_col[uid] for uid in self._active_uids]
            try:
                # Fast vectorized assignment
                self._matrix[self._head_idx, target_cols] = payload_i['data']
                payload_o = {
                    'snapshot': self._net_snapshot,
                    'tick_id': self._tick_id,
                    'data': payload_i['data']
                }
                self._secr.send_evt(EvtType.ICMP_TICK_READY, payload_o)
            except Exception as e:
                print(f"[BufferICMP] Ingest failed: {e}")

            # If the time of agregation, calc and send agregated data
            # Calc agregated data by 1/3/10 minute windows and send data into event
            evt_map = {
                EvtType.TICK_8:   (RollWin.MIN_1,  EvtType.ICMP_AGR_WIN_1M_READY),
                EvtType.TICK_24:  (RollWin.MIN_3,  EvtType.ICMP_AGR_WIN_3M_READY),
                EvtType.TICK_120: (RollWin.MIN_10, EvtType.ICMP_AGR_WIN_10M_READY),
            }
            if evt.evt_type in list(evt_map.keys()):
                win, evt = evt_map[evt.payload['tick_type']]
                agr_data = self._get_agr_win_data(win)
                payload_agr = {
                    'snapshot': self._net_snapshot,
                    'tick_id':  self._tick_id,
                    'data':     agr_data
                }
                self._agr_win[win].insert(0, payload_agr)
                self._agr_win[win].pop()
                self._secr.send_evt(evt, payload_agr)


    # --- NET TOPOLOGY & MEMORY ---

    def _sync_topology(self, evt: Frame) -> None:
        """Updates matrix schema and mapping based on NetworkTopology."""
        with self._lock:
            self._net_snapshot = evt.payload["snapshot"]
            new_uids_set = set(self._net_snapshot.tab.keys())
            curr_uids_set = set(self._uid_to_col.keys())

            # Remove deleted: Wipe columns and free slots
            for uid in (curr_uids_set - new_uids_set):
                col = self._uid_to_col.pop(uid)
                self._matrix[:, col] = np.nan # clean slot
                self._free_slots.append(col)

            # Add new uids: Find free slots or create new slots
            for uid in (new_uids_set - curr_uids_set):
                if not self._free_slots:
                    self._expand_matrix()
                col = self._free_slots.pop()
                self._uid_to_col[uid] = col

            # Finalize order
            self._active_uids = list(self._net_snapshot.tab.keys())
            if len(self._free_slots) > self._tools.config.BUF_ICMP_SPARE_COLS_MAX:
                self._compact_matrix()
            
            payload = {"snapshot": self._net_snapshot, "uid_to_col": self._uid_to_col.copy()}
            self._secr.send_evt(EvtType.ICMP_BUF_NEW_NET_VER_READY, payload)

    def _expand_matrix(self) -> None:
        """Extends matrix width by 100 columns."""
        with self._lock:
            ext = np.full((1200, 100), np.nan, dtype=np.float16)
            old_w = self._matrix.shape[1]
            self._matrix = np.hstack([self._matrix, ext])
            self._free_slots.extend(range(old_w + 99, old_w - 1, -1))

    def _compact_matrix(self) -> None:
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
    
    def _get_agr_win_data(self, window: RollWin) -> dict[str, any]:
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

            data = {
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
            raw_cv = np.nanstd(calc_data, axis=0) / data["avg"]
            
            # Zero RTT Anomaly checking
            inf_mask = np.isinf(raw_cv)
            if np.any(inf_mask):
                bad_uids = [self._active_uids[i] for i in np.where(inf_mask)[0]]
                err = f"Data corruption or scanner failure: RTT is zero. bad_uids: {bad_uids}"
                self._secr.send_err_app(err)

            # Clean up CV: replace Inf/NaN with proper NaN
            data["cv"] = np.where(np.isfinite(raw_cv), raw_cv, np.nan)

            # Quality Gate: if sample_counts < min_samples -> NaN
            quality_mask = sample_counts < min_samples
            for key in data:
                if isinstance(data[key], np.ndarray):
                    # Only apply to float arrays to preserve NaN support
                    if data[key].dtype.kind in 'fc':
                        data[key][quality_mask] = np.nan
            return data

    def _get_agr_db_10m_data(self, time: int) -> dict[str, np.ndarray]:
        """Aggregates full 10-minute matrix for SQL export."""
        with self._lock:
            data = self._matrix.copy()
            uid_to_col = self._uid_to_col.copy()
            snapshot = self._net_snapshot

        # Masks for data filtering
        valid_mask = data >= 0   # Real RTT values
        timeout_mask = data < 0  # Timeouts (-1)
        
        # Data preparation (Ignore -1 and NaN for mathematical stats)
        calc_data = np.where(valid_mask, data, np.nan)

        # Returns a 2D array [5, N_devices]
        perc_values = np.nanpercentile(calc_data, [5, 25, 50, 75, 95], axis=0)
        
        with np.errstate(all='ignore'):
            data = {
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
            return {
                "snapshot":   snapshot,
                "uid_to_col": uid_to_col,
                "end_time":   time,
                "data":       data
            }
        
    def _get_raw_db_10m_data(self, time: int) -> dict[str, any]:
        """
        Prepares a 10-minute raw data package for the DB Staging Area.
        Returns a dict with binary matrix, UID mapping, and start timestamp.
        """
        with self._lock:
            # Reorder so the oldest row is first, newest is last
            linear_matrix = np.roll(self._matrix, shift=-(self._head_idx + 1), axis=0)
            return {
                "snapshot":  self._net_snapshot,
                "uid_to_col":self._uid_to_col.copy(),
                "end_time":  time,
                "blob":      linear_matrix.tobytes() 
            }

    # TODO CodeMe    
    def _get_uids_by_latency(self) -> list[int]:
        return []

    def _get_max_streak(m_2d) -> NDArray[np.int32]:
        # Used into _calc_*(). Vertical stack a False row to handle edge cases at the start
        m = np.vstack([np.zeros(m_2d.shape[1], dtype=bool), m_2d])
        idx = np.where(~m, 0, 1)
        # Iterative prefix sum that resets on False (non-timeout) values
        for i in range(1, idx.shape[0]):
            idx[i] *= (idx[i-1] + 1)
        return np.max(idx, axis=0)
