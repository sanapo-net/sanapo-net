# tests/core/mock_scanner_icmp.py
from __future__ import annotations
import threading
import numpy as np
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from tests.common import PersistentGenerator

if TYPE_CHECKING:
    from core.config import Config
    from core.enums import TickInterval

class MockScannerICMP:
    """
    Simulation engine that mimics real ICMP scanning behavior.
    Uses stability and peak RTT metrics to generate reproducible RTT data.
    """
    def __init__(self, config: Config, hosts_meta: list[tuple[int, float, float]] = None):
        self._config = config
        self._results = []
        self._lock = threading.Lock()
        
        # Keep the executor to simulate asynchronous behavior
        self._executor = ThreadPoolExecutor(max_workers=config.ICMP_THREADS_MIN)
        
        # Meta storage: {uid: (stability, peak_rtt)}
        # stability 1.0 (perfect) to 0.0 (offline)
        self._meta = {m[0]: (m[1], m[2]) for m in hosts_meta} if hosts_meta else {}
        
        # Base generator for unknown hosts and random logic
        self._gen = PersistentGenerator("mock_scanner_logic")

    def get_queue_depth(self) -> int:
        """Returns the number of pending batch tasks."""
        return self._executor._work_queue.qsize()
    
    def pop_results(self) -> list:
        """Thread-safe retrieval of simulated results."""
        with self._lock:
            captured_data = self._results
            self._results = [] 
            return captured_data

    def execute(self, active_groups: dict, tick_id: int):
        """Implements the same batching logic as the real ScannerICMP."""
        # Calculate total hosts once for the Blitz-batching logic
        total_in_tick = sum(
            len(devs) 
            for t_map in active_groups.values() 
            for devs in t_map.values()
        )

        # Directly iterate over intervals (Manager guaranteed the order)
        for interval, timeout_map in active_groups.items():
            
            for timeout, device_list in timeout_map.items():
                cursor = 0
                total_devs = len(device_list)

                while cursor < total_devs:
                    # Fixed batch size for simplicity in mock
                    b_size = 20 
                    current_batch_len = min(total_devs - cursor, b_size)
                    
                    batch = []
                    for i in range(cursor, cursor + current_batch_len):
                        dev = device_list[i]
                        # We inject the interval value to calculate the 5% peak later
                        batch.append({
                            "uid": dev["uid"],
                            "ip": dev["ip"],
                            "tick_id": tick_id,
                            "interval_val": interval.value,
                            "rtt": np.nan
                        })
                    
                    self._executor.submit(self._mock_ping_worker, batch, timeout)
                    cursor += current_batch_len

    def _mock_ping_worker(self, batch: list, timeout: float):
        """Simulates network latency and packet loss logic."""
        for dev in batch:
            uid = dev["uid"]
            
            # 1. Handle meta-data for known/unknown hosts
            if uid not in self._meta:
                # Random stability between 0.1 and 0.98
                stability = self._gen._rnd.uniform(0.1, 0.98)
                # Default peak RTT is 5% of its scan interval
                peak_rtt = dev["interval_val"] * 0.05
                self._meta[uid] = (stability, peak_rtt)
            
            stability, peak_rtt = self._meta[uid]

            # 2. Packet loss simulation
            # Higher stability means lower chance of returning -1.0
            if stability <= 0 or self._gen._rnd.random() > stability:
                dev["rtt"] = -1.0
                continue

            # 3. RTT Generation using triangular distribution
            # Jitter increases as stability decreases
            jitter_factor = (1.0 - stability) * 0.8
            min_rtt = max(0.0003, peak_rtt * (1 - jitter_factor))
            max_rtt = min(timeout, peak_rtt * (1 + jitter_factor * 2))
            
            # Generate reproducible RTT based on the host's peak
            rtt = self._gen._rnd.triangular(min_rtt, max_rtt, peak_rtt)
            
            # Final RTT assignment with timeout protection
            dev["rtt"] = round(rtt, 4) if rtt < timeout else -1.0
            
            # Cleanup internal helper key before returning to buffer
            dev.pop("interval_val", None)

        with self._lock:
            self._results.extend(batch)
