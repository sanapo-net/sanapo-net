# core/scanner/manager_icmp.py
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from main import Tools
    from core.secretary import Secretary
    from core.network.network_manager import NetworkSnapshot

from collections import defaultdict
from typing import Any
import json # TODO del it in realise. It's for debug

from core.enums import EvtType, Priority, TickInterval, SpeedShiftICMP
from core.protocol import Frame
from core.scanner.scanner_icmp import ScannerICMP
from core.secretary import Secretary
from core.logger import Logger


# TODO sorting!

class ManagerICMP():
    def __init__(self, tools: Tools, secr: Secretary, logger: Logger) -> None:
        self._tools: Tools = tools
        self._secr: Secretary = secr
        self._log: Logger = logger
        
        self._scanner: ScannerICMP = ScannerICMP(self._tools.config)
        
        self._snapshot: NetworkSnapshot = None

        min_interval = TickInterval.SEC_05.value
        max_interval = TickInterval.SEC_8.value
        self._intervals = [t for t in TickInterval if min_interval <= t.value <= max_interval]
        self._speed_shift: SpeedShiftICMP = SpeedShiftICMP.NORMAL
        self._tick_schedule = self._prepare_schedule()
        self._scan_profiles: dict[SpeedShiftICMP, dict[TickInterval, list[dict[str, any]]]] = None
        print(json.dumps(self._tick_schedule, indent=4, default=str)) # TODO del it in realise

        self._secr.configure_subscriptions(events={
            EvtType.TICK_05: self._on_tick,
            EvtType.TICK_1: self._on_tick,
            EvtType.TICK_2: self._on_tick,
            EvtType.TICK_4: self._on_tick,
            EvtType.TICK_8: self._on_tick,
            EvtType.NETWORK_NEW_VER: self._on_new_net_ver,
            EvtType.ICMP_UIDS_BY_LATENCY_READY: self._on_uids_by_latency,
            EvtType.ICMP_NEW_INTERVALS: self._on_speed_changed
        })

    # --- On events ---

    # ICMP_NEW_INTERVALS
    def _on_speed_changed(self, frame: Frame) -> None:
        """Speed mode change event."""
        self._speed_shift = frame.payload["icmp_speed_shift"]
        
    # TICK_* (05-8)
    def _on_tick(self, frame: Frame) -> None:
        """Send data from scaner to buffer and put to scanner new job"""
        tick_type = frame.evt_type
        tick_id = frame.payload["tick_id"]
        scan_results = self._scanner.pop_results()
        # Check scan queue overloaded
        queue_depth = self._scanner.get_queue_depth()
        if self._scanner.get_queue_depth() > self._tools.config.ICMP_SCAN_QUEUE_THRESHOLD:
            text = f"Scan skip at tick {tick_id}. Queue overloaded: {queue_depth} tasks."
            self._log.wrn(text)
            return
        active_groups = {}
        for interval in self._tick_schedule[self._speed_shift][tick_type]:
            active_groups[interval] = self._scan_profiles[self._speed_shift][interval]
        self._scanner.execute(active_groups, tick_id)
        payload = {"data": scan_results}
        self._secr.send_evt(EvtType.ICMP_RAW_READY, payload=payload)

    # NETWORK_NEW_VER 
    def _on_new_net_ver(self, frame: Frame) -> None: 
        """checks net ver and build new sorted _scan_profiles."""
        frame_snapshot = frame.payload.get("snapshot", None)
        if not frame_snapshot:
            self._log.err("payloadd with out 'snapshot'", frame, "SMe")
            return
        if frame_snapshot.version < self._tools.network.snapshot.version:
            return # Wait new evt new net ver
        elif frame_snapshot.version > self._tools.network.snapshot.version:
            text = "The version received is newer than the network version."
            self._log.err(text, frame, "SMe")
            return
        else:
            self._get_scan_profiles_by_net_tab(frame_snapshot.tab)
            self._sort_scan_profiles()

    # ICMP_UIDS_BY_LATENCY_READY
    def _on_uids_by_latency(self, frame: Frame) -> None:
        """gets uids_by_latency from BufferICMP"""
        temp_score = frame.payload.get("uids_by_latency", None)
        if not temp_score:
            self._log.err("uids_by_latency was not applied", frame, "Se")
            return
        self._uids_by_latency = temp_score
        self._sort_scan_profiles()

    # --- Service ---

    def _shift_interval(self, current_tick: TickInterval, shift: SpeedShiftICMP) -> TickInterval:
        """
        Shifts the interval according to the selected speed mode.
        Does not extend beyond self._intervals (SEC_05 - SEC_8).
        """
        try:
            current_idx = self._intervals.index(current_tick)
            new_idx = current_idx + shift.value
            clamped_idx = max(0, min(new_idx, len(self._intervals) - 1))
            
            return self._intervals[clamped_idx]
        except ValueError:
            return current_tick

    def _get_scan_profiles_by_net_tab(self, tab: dict[int, dict[str, Any]]) -> None:
        """
        Groups devices from the network table by their scan intervals.
        Args: tab: Dictionary where key is UID and value is device data.
        Returns: Dictionary where key is TickInterval and value is a list of device dicts.
        """
        # init
        self._scan_profiles = {s: defaultdict(list) for s in SpeedShiftICMP}
        
        for uid, dev_data in tab.items():
            # Retrieve the interval object (TickInterval)
            orig_interval = dev_data.get("icmp_interval")
            if not isinstance(orig_interval, TickInterval):
                self._log.err(f"Invalid icmp_interval for uid:{uid}")
                continue

            base_timeout = dev_data.get("timeout",self._tools.settings.scan.timeouts[orig_interval])
            
            # Data for NORMAL, SLOWER interval
            margin_norm = self._tools.config.SCAN_ICMP_TIMEOUT_MIN_MARGIN[orig_interval]
            timeout_norm = min(base_timeout, orig_interval.value - margin_norm)
            data_norm = {
                "uid": dev_data["uid"],
                "ip": dev_data["ip"],
                "timeout": timeout_norm,
            }
            self._scan_profiles[SpeedShiftICMP.NORMAL][orig_interval].append(data_norm)
            self._scan_profiles[SpeedShiftICMP.SLOWER][orig_interval].append(data_norm)

            # Data for FASTER interval
            fast_interval = self._shift_interval(orig_interval, SpeedShiftICMP.FASTER)
            margin_fast = self._tools.config.SCAN_ICMP_TIMEOUT_MIN_MARGIN[fast_interval]
            timeout_fast = min(base_timeout, fast_interval.value - margin_fast)
            data_fast = {
                "uid": dev_data["uid"],
                "ip": dev_data["ip"],
                "timeout": timeout_fast,
            }
            self._scan_profiles[SpeedShiftICMP.FASTER][orig_interval].append(data_fast)
        
        for mode in self._scan_profiles:
            self._scan_profiles[mode] = dict(self._scan_profiles[mode])


    def _sort_scan_profiles(self) -> None:
        """sorts all lists in _scan_profiles by timeout and latency"""
        for speed_shift in self._scan_profiles:
            for interval in speed_shift:
                for uid_list in interval:
                    pass # sorting

    def _prepare_schedule(self) -> dict:
        """
        Creates a nested schedule map:
        full_map[SpeedShiftICMP][EvtType] -> [TickInterval, ...] 
        In the lists: [longest_interval, ..., shortest_inteval]
        Logic: Shifts the group's effective interval index based on the speed multiplier
        and checks if the current physical tick is a multiple of that interval.
        """
        # Mapping: Physical Tick Event -> Physical Interval Value
        tick_to_int = {
            EvtType.TICK_05: TickInterval.SEC_05,
            EvtType.TICK_1:  TickInterval.SEC_1,
            EvtType.TICK_2:  TickInterval.SEC_2,
            EvtType.TICK_4:  TickInterval.SEC_4,
            EvtType.TICK_8:  TickInterval.SEC_8,
        }
        full_map = {}

        # Iterate through speed modes: FASTER (1), NORMAL (0), SLOWER (-1)
        for shift in SpeedShiftICMP:
            shift_map = {}
            
            # Process each physical tick generated by the Ticker
            for phys_evt, phys_int in tick_to_int.items():
                active_groups = []
                
                # Check each device group (by their base interval)
                for group_int in self._intervals:
                    # 1. Find the base interval index in the "rails" [0.5 ... 8.0]
                    idx = self._intervals.index(group_int)
                    
                    # 2. Apply shift: FASTER(1) -> idx-1 (faster), SLOWER(-1) -> idx+1 (slower)
                    # Clamping the index within available interval bounds
                    new_idx = max(0, min(idx - shift.value, len(self._intervals) - 1))
                    
                    # 3. Determine the effective interval for the current speed mode
                    effective_int = self._intervals[new_idx]
                    
                    # 4. Check if the physical tick aligns with the effective interval
                    # Using small epsilon for float modulo safety
                    if (phys_int.value + 0.001) >= effective_int.value and \
                       (phys_int.value % effective_int.value) < 0.01:
                        active_groups.append(group_int)
                
                shift_map[phys_evt] = active_groups
            
            full_map[shift] = shift_map
            
        return full_map
"""
Generated `full_map` structure for intervals [0.5, 1.0, 2.0, 4.0, 8.0]:
{
    # --- FASTER (Groups shift to shorter intervals) ---
    # Example: SEC_1 acts like SEC_05, SEC_8 acts like SEC_4
    SpeedShiftICMP.FASTER: {
        EvtType.TICK_05: [SEC_05, SEC_1],
        EvtType.TICK_1:  [SEC_05, SEC_1, SEC_2],
        EvtType.TICK_2:  [SEC_05, SEC_1, SEC_2, SEC_4],
        EvtType.TICK_4:  [SEC_05, SEC_1, SEC_2, SEC_4, SEC_8],
        EvtType.TICK_8:  [SEC_05, SEC_1, SEC_2, SEC_4, SEC_8]
    },

    # --- NORMAL (Standard 1:1 mapping) ---
    # Groups trigger exactly on their physical time
    SpeedShiftICMP.NORMAL: {
        EvtType.TICK_05: [SEC_05],
        EvtType.TICK_1:  [SEC_05, SEC_1],
        EvtType.TICK_2:  [SEC_05, SEC_1, SEC_2],
        EvtType.TICK_4:  [SEC_05, SEC_1, SEC_2, SEC_4],
        EvtType.TICK_8:  [SEC_05, SEC_1, SEC_2, SEC_4, SEC_8]
    },

    # --- SLOWER (Groups shift to longer intervals) ---
    # Example: SEC_05 acts like SEC_1, SEC_4 acts like SEC_8
    SpeedShiftICMP.SLOWER: {
        EvtType.TICK_05: [], 
        EvtType.TICK_1:  [SEC_05],
        EvtType.TICK_2:  [SEC_05, SEC_1],
        EvtType.TICK_4:  [SEC_05, SEC_1, SEC_2],
        EvtType.TICK_8:  [SEC_05, SEC_1, SEC_2, SEC_4, SEC_8] # SEC_8 is clamped here
    }
}
"""