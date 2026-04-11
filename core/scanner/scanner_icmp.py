# core/scanner/scanner_icmp.py
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from main import Tools
    from core.secretary import Secretary
    from core.network.network_manager import NetworkSnapshot

from core.enums import EvtType, Priority
from core.protocol import Frame

class ScannerICMP():
    def __init__(self, tools:Tools, secr:Secretary) -> None:
        self._secr: Secretary = secr
        self._tools: Tools = tools
        self._snapshot: NetworkSnapshot = None
        self._lvl_map: dict[Priority, list[int]] = {}
        self._net_tab: dict[int, dict] = {}
        self._uid_to_col: dict[Priority, int] = {} 
        self._intervals: dict[Priority, list[int]] = self._tools.settings.icmp.intervals
        self._uids_by_latency: list[int] = []
        all_ticks = list(EvtType)[1:-2]
        self._max_tick_to_ticks: dict[EvtType, list[EvtType]] = {
            tick: all_ticks[i:] for i, tick in enumerate(all_ticks)
        }
        self._priorities_map: dict[Priority, list[int]] = {
            Priority.HIGH:[],
            Priority.MEDIUM:[],
            Priority.LOW:[]
        }
        subscriptions = {
            EvtType.TICK_05: self._on_tick,
            EvtType.TICK_1: self._on_tick,
            EvtType.TICK_2: self._on_tick,
            EvtType.TICK_4: self._on_tick,
            EvtType.TICK_8: self._on_tick,
            EvtType.ICMP_BUF_NEW_NET_VER_READY: self._on_new_net_ver,
            EvtType.ICMP_NEW_INTERVALS: self._on_new_intervals,
            EvtType.ICMP_UIDS_BY_LATENCY_READY: self._on_uids_by_latency_ready
        }
        self._secr.configure_subscriptions(subscriptions)
    

    def _on_new_intervals(self, msg:Frame = None):
        if msg.payload.get("intervals"):
            self._intervals = msg.payload["intervals"]
        else:
            self._intervals = self._tools.settings.icmp.intervals


    def _on_uids_by_latency_ready(self, msg:Frame):
        # Update our internal rating map (from payload or direct buffer call)
        if msg.payload.get("uids_by_latency"):
            self._uids_by_latency = msg.payload["uids_by_latency"]
        else:
            er = f"ICMP_UIDS_BY_LATENCY_READY: msg.payload['uids_by_latency'] don't exist"
            self._secr.send_err_app(er)


    def _on_new_net_ver(self, msg:Frame):
        self._snapshot = msg.payload["snapshot"]
        self._lvl_map = msg.payload["snapshot"].lvls
        self._net_tab = msg.payload["snapshot"].tab
        self._uid_to_col = msg.payload["uid_to_col"]
        
        
    def _on_tick(self, msg:Frame):
        tick_id = msg.payload["tick_id"]
        scan_list = []
        for key, uids_for_priority in self._priorities_map.items():
            if msg.evt_type in self._max_tick_to_ticks[self._intervals[key]]:
                scan_list + uids_for_priority
        if scan_list:
            scan_queue = self._get_scan_queue(scan_list)
            data = self._scan(scan_queue)
            payload = {"data":data, "snapshot":self._snapshot, "tick_id":tick_id}
            self._secr.send_evt(EvtType.ICMP_RAW_READY, payload)


    # === TODO CodeMe ===
    def _scan(self, scan_queue) -> list:
        pass
    
    
    def _get_scan_queue(self, uids_to_scan: list[int]) -> list[int]:
        """Rebuilds the scan sequence: stable & fast first, unknown/dead last."""
        # Fetch fresh rating from Buffer via _sync_topology()
        stats = self._uids_by_latency
        
        # Sort the provided UIDs using the latency map as a key
        # float('inf') ensures new UIDs (not in stats) go to the end
        sorted_queue = sorted(
            uids_to_scan, 
            key=lambda uid: stats.get(uid, float('inf'))
        )
        return sorted_queue
