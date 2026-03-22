# core/data_buffer.py
import threading
from collections import OrderedDict

class DataBuffer:
    def __init__(self, history_size=1000):
        self._lock = threading.Lock()
        self._history = OrderedDict()
        self._history_size = history_size
        self._tick_counter = 0
        self._raw_data = {} # Engine put data here

    def write_raw(self, key, val):
        with self._lock: self._raw_data[key] = val

    def compute_tick(self):
        """do it every tick"""
        with self._lock:
            self._tick_counter += 1
            tid = self._tick_counter
            snap = self._raw_data.copy()

        # calculations will be here
        res = {"val": snap.get("data", 0) * 10, "tid": tid}

        with self._lock:
            self._history[tid] = res
            if len(self._history) > self._history_size:
                self._history.popitem(last=False)
        return tid

    def get_data(self, tid):
        with self._lock:
            return self._history.get(tid)