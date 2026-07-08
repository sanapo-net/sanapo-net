# modules/common/scan/pool_watchdog.py
from __future__ import annotations

import time
import threading
from concurrent.futures import Future
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sanapo.logger import Logger

TrackList = list[tuple[float, Future, list[any], callable[[list[any]], None], str]]

class PoolWatchdog:
    """Monitors running tasks and recovers from stalled threads."""

    def __init__(self, logger: Logger) -> None:
        self._logger: Logger = logger
        self._tracked: TrackList = []
        self._lock = threading.Lock()

    def track(self,
        future: Future,
        batch: list[any],
        ttl: float,
        on_timeout: callable[[list[any]], None],
        group_name: str = "UnknownScanner",
    ) -> None:
        """
        Registers a task for deadline monitoring.

        Args:
            future: Future object of the submitted task.
            batch: list of device dicts being processed in this task.
            ttl: maximum allowed lifetime of the task (seconds).
            on_timeout: callback to mark batch as lost if deadline exceeded.
            group_name: human-readable pool-category identifier for logging.
        """
        with self._lock:
            self._tracked.append((time.time() + ttl, future, batch, on_timeout, group_name))

    def check_and_recover(self) -> None:
        """Scans all tracked tasks and triggers recovery for those exceeding deadline."""
        to_recover = []
        still_active: TrackList = []
        
        # Checking
        with self._lock:
            for item in self._tracked:
                deadline, future, batch, on_timeout, group_name = item
                if future.done():
                    continue
                if time.time() > deadline:
                    to_recover.append((batch, on_timeout, group_name))
                else:
                    still_active.append(item)
            self._tracked = still_active

        # Recovering
        for batch, on_timeout, group_name in to_recover:
            self._logger.wrn(f"WTCH_DOG: one thread dead group '{group_name}'")
            try:
                on_timeout(batch)
            except Exception as e:
                self._logger.err(f"WTCH_DOG error in '{group_name}': {e}")
