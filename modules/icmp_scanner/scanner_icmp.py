# modules/icmp_scanner/scanner_icmp.py
from __future__ import annotations
import queue
import socket
from icmplib import multiping
from typing import TYPE_CHECKING, Any, Callable

from modules.common.scan.pool_watchdog import PoolWatchdog
from modules.common.scan.thread_pool_manager import ThreadPoolManager

if TYPE_CHECKING:
    from common.config import Config
    from sanapo.logger import Logger


class ScannerICMP:
    """ICMP scanner that uses a shared thread pool and watchdog for resilience."""

    def __init__(
        self,
        config: Config,
        pool_manager: ThreadPoolManager,
        watchdog: PoolWatchdog,
        logger: Logger,
    ) -> None:
        """
        Initializes scanner with external thread pool, watchdog and logger.

        Args:
            config: program configuration object.
            pool_manager: shared thread pool manager.
            watchdog: pool watchdog for hung tasks.
            logger: logger instance from framework.
        """
        self._config = config
        self._pool = pool_manager
        self._watchdog = watchdog
        self._log = logger

        # Thread-safe queue for scan results.
        self._results_queue: queue.Queue = queue.Queue()

        # Check if raw sockets are available.
        self._use_raw = self._check_raw_access()

        # Callback for watchdog timeouts.
        self._on_batch_timeout: Callable[[list[dict[str, Any]]], None] = (self._handle_icmp_timeout)

    def _check_raw_access(self) -> bool:
        """
        Checks for sufficient privileges to create Raw Sockets.

        Returns:
            True if raw sockets can be created, False otherwise.
        """
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
            s.close()
            return True
        except PermissionError:
            return False

    def _handle_icmp_timeout(self, batch: list[dict[str, Any]]) -> None:
        """
        Marks all devices in the batch as lost (rtt = -1.0) due to timeout.

        Args:
            batch: list of device dicts with keys: uid, ip, tick_id, timeout.
        """
        for dev in batch:
            dev["rtt"] = -1.0
            self._results_queue.put(dev)

    def execute(
        self,
        batches: dict[str, list[list[dict[str, Any]]]],
        ttl_map: dict[str, float],
    ) -> None:
        """
        Sends pre-built batches to the thread pool for scanning.

        Args:
            batches: mapping group_name -> list of batches
                     (each batch is a list of device dicts).
            ttl_map: mapping group_name -> time-to-live (seconds)
                     for tasks of that category.
        """
        for category, batch_list in batches.items():
            ttl = ttl_map.get(category, self._config.SCAN_ICMP_DEFAULT_TTL)
            for batch in batch_list:
                if not batch:
                    continue
                # Timeout is taken from the first device (all share the same timeout).
                timeout = batch[0].get("timeout", 2.0)
                try:
                    future = self._pool.submit(
                        self._ping_worker,
                        (batch, timeout),
                        category=category,
                        ttl=ttl,
                        timeout=timeout,
                    )
                    self._watchdog.track(
                        future=future,
                        batch=batch,
                        ttl=ttl,
                        on_timeout=self._on_batch_timeout,
                        group_name=f"ICMP_{category}"
                    )
                except RuntimeError as exc:
                    # No free slot in pool – mark whole batch as lost immediately.
                    self._log.wrn(
                        f"ICMP scanner: failed to submit batch "
                        f"in category '{category}': {exc}"
                    )
                    self._handle_icmp_timeout(batch)

    def pop_results(self) -> list[dict[str, Any]]:
        """
        Retrieves all accumulated scan results from the internal queue.

        Returns:
            list of device result dicts with updated 'rtt' field.
        """
        # First, let the watchdog recover any hung tasks.
        self._watchdog.check_and_recover()

        results = []
        while not self._results_queue.empty():
            try:
                results.append(self._results_queue.get_nowait())
            except queue.Empty:
                break
        return results

    def _ping_worker(self, batch: list[dict[str, Any]], timeout: float) -> None:
        """
        Worker function: sends ICMP echo requests and updates rtt in batch dicts.

        Args:
            batch: list of device dicts with keys: uid, ip, timeout.
            timeout: network timeout in seconds.
        """
        try:
            addresses = [dev["ip"] for dev in batch]
            hosts = multiping(addresses, timeout=timeout, privileged=self._use_raw)
            for i, host in enumerate(hosts):
                batch[i]["rtt"] = (host.avg_rtt / 1000.0 if host.is_alive else -1.0)
        except Exception:
            for dev in batch:
                dev["rtt"] = -1.0

        for dev in batch:
            self._results_queue.put(dev)