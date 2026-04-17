# core/scanner/scanner_icmp.py
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from core.config import Config
    from core.enums import TickInterval

from icmplib import multiping

import socket
import threading
import numpy as np
from concurrent.futures import ThreadPoolExecutor


class ScannerICMP:
    # TODO move it to config
    BATCH_SIZE_SMALL_NET = 15
    NET_SIZE_THRESHOLD = 500
    BATCH_CONFIG_LARGE = [
        (10, 80),  # Top 20% (highest priority) -> batch size 10
        (20, 50),  # Next 30% -> batch size 20
        (50, 0)    # Remaining 50% (background/slow) -> batch size 50
    ]
    THREADS_MIN = 20
    THREADS_MAX = 100
    QUEUE_GROWTH_STEP = 15  # Queue threshold for pool scaling

    def __init__(self):
        self._results = []
        self._lock = threading.Lock()
        
        # Dynamic thread management
        self._current_max_workers = self.THREADS_MIN
        self._executor = ThreadPoolExecutor(max_workers=self._current_max_workers)

        # Execution mode detection (Raw vs User)
        self._use_raw = self._check_raw_access()

    def get_queue_depth(self) -> int:
        """Возвращает текущую загруженность сканера (кол-во задач в очереди)."""
        return self._executor._work_queue.qsize()
    
    def pop_results(self) -> list:
        """Returns the current scanner workload (number of pending tasks in the queue)."""
        with self._lock:
            if not self._results:
                return []
            captured_data = self._results
            self._results = [] 
            return captured_data

    def execute(self, active_groups: dict[TickInterval, dict[float, list]], tick_id: int):
        """
        Processes pre-structured device groups for the current tick.
        
        Args:
            active_groups: Nested structure { Interval: { Timeout: [device_data, ...] } }
            tick_id: Unique identifier or timestamp of the current tick.
        """
        self._adjust_threads()
        
        # Calculate total hosts once for the Blitz-batching logic
        total_in_tick = sum(
            len(devs) 
            for t_map in active_groups.values() 
            for devs in t_map.values()
        )

        # Directly iterate over intervals (Manager guaranteed the order)
        for timeout_map in active_groups.values():
            
            for timeout, device_list in timeout_map.items():
                cursor = 0
                total_devs = len(device_list)
                
                while cursor < total_devs:
                    # Blitz batch size logic (10/20/50)
                    remaining = total_devs - cursor
                    b_size = self._get_dynamic_batch_size(remaining, total_in_tick)
                    
                    # Tail balancing (Greedy tail)
                    current_batch_len = remaining if remaining < (b_size * 1.5) else b_size
                    
                    # Create lightweight worker-dicts (Zero-mutation for the Cache)
                    batch = []
                    for i in range(cursor, cursor + current_batch_len):
                        dev = device_list[i]
                        batch.append({
                            "uid": dev["uid"],
                            "ip": dev["ip"],
                            "tick_id": tick_id,
                            "rtt": np.nan
                        })
                    
                    # Submit to pool
                    self._executor.submit(self._ping_worker, batch, timeout)
                    cursor += current_batch_len


    def _check_raw_access(self) -> bool:
        """Checks for sufficient privileges to create Raw Sockets."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
            s.close()
            return True
        except PermissionError:
            return False

    def _adjust_threads(self):
        """Dynamically expands the thread pool in case of congestion."""
        depth = self.get_queue_depth()
        if depth > self.QUEUE_GROWTH_STEP and self._current_max_workers < self.THREADS_MAX:
            self._current_max_workers = min(self.THREADS_MAX, self._current_max_workers + 10)
            self._executor._max_workers = self._current_max_workers
            # Python 3.7+ supports auto changing max_workers

    def _get_dynamic_batch_size(self, current_count: int, total: int) -> int:
        """Calculates batch size based on dataset size and scanning progress."""
        if total < self.NET_SIZE_THRESHOLD:
            return self.BATCH_SIZE_SMALL_NET
        
        percent_left = (current_count / total) * 100
        for size, threshold in self.BATCH_CONFIG_LARGE:
            if percent_left > threshold:
                return size
        return self.BATCH_SIZE_SMALL_NET

    def _ping_worker(self, batch: list, timeout: float):
        """Thread worker: fanning out packets and collecting responses."""
        try:
            # Bulk pinging using icmplib
            addresses = [d['ip'] for d in batch]
            timeouts = [d['timeout'] for d in batch]
            hosts = multiping(addresses, timeout=timeout, privileged=self._use_raw)
            
            for i, host in enumerate(hosts):
                # RTT in seconds (float16) or -1.0 on packet loss
                batch[i]["rtt"] = host.avg_rtt / 1000 if host.is_alive else -1.0
                
        except Exception:
            # Mark the entire batch as lost in case of a critical socket failure
            for dev in batch:
                dev["rtt"] = -1.0
                
        with self._lock:
            self._results.extend(batch)
