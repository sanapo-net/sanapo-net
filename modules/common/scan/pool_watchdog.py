# modules/common/scan/pool_watchdog.py
from __future__ import annotations

import time
import threading
from concurrent.futures import Future
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sanapo.logger import Logger

class PoolWatchdog:
    """
    Monitors running tasks and recovers from stalled threads.
    """

    def __init__(self, logger: Logger) -> None:
        """
        Stores a logger reference for warning messages.

        Args:
            logger: logger instance from the framework.
        """
        self._logger: Logger = logger
        self._tracked: list[
            tuple[float, Future, list[any], callable[[list[any]], None], str]
        ] = []
        self._lock = threading.Lock()

    def track(
        self,
        future: Future,
        batch: list[any],
        ttl: float,
        on_timeout: callable[[list[any]], None],
        scanner_name: str = "UnknownScanner",
        grace_period: float = 2.0,
    ) -> None:
        """
        Registers a task for deadline monitoring.

        Args:
            future: Future object of the submitted task.
            batch: list of device dicts being processed in this task.
            ttl: maximum allowed lifetime of the task (seconds).
            on_timeout: callback to mark batch as lost if deadline exceeded.
            scanner_name: human-readable scanner identifier for logging.
            grace_period: extra time added to ttl before triggering watchdog (seconds).
        """
        deadline = time.time() + ttl + grace_period
        with self._lock:
            self._tracked.append(
                (deadline, future, batch, on_timeout, scanner_name)
            )

    def check_and_recover(self) -> None:
        """
        Scans all tracked tasks and triggers recovery for those exceeding deadline.
        """
        still_active: list[
            tuple[float, Future, list[any], callable[[list[any]], None], str]
        ] = []

        with self._lock:
            for deadline, future, batch, on_timeout, scanner_name in self._tracked:
                if future.done():
                    continue

                if time.time() > deadline:
                    self._logger.wrn(
                        f"WTCH_DOG: one thread dead in pool '{scanner_name}'"
                    )
                    try:
                        on_timeout(batch)
                    except Exception as e:
                        self._logger.err(
                            f"WTCH_DOG critical error in '{scanner_name}': {e}"
                        )
                else:
                    still_active.append(
                        (deadline, future, batch, on_timeout, scanner_name)
                    )

            self._tracked = still_active