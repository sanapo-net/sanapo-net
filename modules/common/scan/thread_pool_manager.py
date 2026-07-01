# modules/common/scan/thread_pool_manager.py
from __future__ import annotations

import threading
from concurrent.futures import Future
from queue import Queue
from typing import Any, Callable


class ThreadPoolManager:
    """
    Universal thread pool with named concurrency-limited categories.
    """

    def __init__(self, max_workers: int) -> None:
        """
        Initializes the pool with a fixed upper bound on total threads.

        Args:
            max_workers: maximum number of OS threads allowed (config limit).
        """
        if max_workers < 1:
            raise ValueError("max_workers must be at least 1")
        self._max_workers: int = max_workers
        self._pools: dict[str, threading.BoundedSemaphore] = {}
        self._task_queue: Queue = Queue()
        self._threads: list[threading.Thread] = []
        self._shutdown_flag = threading.Event()
        self._lock = threading.Lock()
        for _ in range(self._max_workers):
            t = threading.Thread(target=self._worker, daemon=True)
            t.start()
            self._threads.append(t)

    def get_max_workers(self) -> int:
        """
        Returns the maximum number of worker threads in the pool.

        Returns:
            Total thread limit.
        """
        return self._max_workers

    def set_max_workers(self, new_limit: int) -> None:
        """Dynamically changes the total number of worker threads."""
        if new_limit < 1:
            raise ValueError("max_workers must be at least 1")
        with self._lock:
            old = self._max_workers
            if new_limit == old:
                return
            delta = new_limit - old
            self._max_workers = new_limit
            if delta > 0:
                for _ in range(delta):
                    t = threading.Thread(target=self._worker, daemon=True)
                    t.start()
                    self._threads.append(t)
            else:
                for _ in range(-delta):
                    self._task_queue.put(None)

    def new_pool(self, name: str, max_concurrent: int) -> None:
        """
        Creates a new category with the given concurrency limit.

        Args:
            name: unique category name (e.g. 'SEC_05').
            max_concurrent: maximum simultaneous tasks allowed in this category.
        """
        with self._lock:
            if name in self._pools:
                raise ValueError(f"Pool '{name}' already exists")
            self._pools[name] = threading.BoundedSemaphore(max_concurrent)

    def close_pool(self, name: str) -> None:
        """
        Removes a category.
        New tasks will be rejected; already running tasks finish normally.

        Args:
            name: category name to remove.
        """
        with self._lock:
            sem = self._pools.pop(name, None)
            if sem is not None:
                while sem.acquire(blocking=False):
                    pass

    def get_pool_size(self, name: str) -> int:
        """Returns the concurrency limit for a category."""
        with self._lock:
            sem = self._pools.get(name)
            if sem is None:
                raise ValueError(f"Pool '{name}' does not exist")
            return sem._initial_value

    def resize_pool(self, name: str, max_concurrent: int) -> None:
        """Changes the category limit; old semaphore is replaced with a new one."""
        with self._lock:
            if name not in self._pools:
                raise ValueError(f"Pool '{name}' does not exist")
            self._pools[name] = threading.BoundedSemaphore(max_concurrent)

    def setup(self, config: dict[str, int]) -> None:
        """
        Batch-updates concurrency limits for multiple categories.

        Args:
            config: mapping {category_name: max_concurrent}.
        """
        for name, limit in config.items():
            if name not in self._pools:
                self.new_pool(name, limit)
            else:
                self.resize_pool(name, limit)

    def available_slots(self, name: str) -> int:
        """
        Returns the number of free slots in the specified category.

        Args:
            name: category name.

        Returns:
            Free slots count (0 if category doesn't exist).
        """
        with self._lock:
            sem = self._pools.get(name)
            return sem._value if sem else 0

    def submit(
        self,
        task: Callable[..., Any],
        args: tuple,
        category: str,
        ttl: float,
        timeout: float,
    ) -> Future:
        """
        Submits a task to the pool under the given category.

        Args:
            task: callable to execute.
            args: positional arguments for the task.
            category: category name for concurrency control.
            ttl: maximum lifetime in seconds (for watchdog tracking).
            timeout: network timeout inside the task
                     (passed to task if needed).

        Returns:
            Future object representing the task result.

        Raises:
            RuntimeError: if no slot is available in the category.
        """
        with self._lock:
            sem = self._pools.get(category)
            if sem is None:
                raise RuntimeError(f"Pool '{category}' does not exist")
            if not sem.acquire(blocking=False):
                raise RuntimeError(f"No free slots in pool '{category}'")

        future: Future = Future()
        self._task_queue.put((task, args, timeout, future, sem))
        return future

    def shutdown(self) -> None:
        """
        Gracefully shuts down all worker threads.
        """
        self._shutdown_flag.set()
        for _ in self._threads:
            self._task_queue.put(None)
        for t in self._threads:
            t.join(timeout=5)

    def _worker(self) -> None:
        """
        Worker thread loop: takes tasks from the queue and executes them.
        """
        while not self._shutdown_flag.is_set():
            item = self._task_queue.get()
            if item is None:
                break
            task, args, timeout, future, sem = item
            try:
                result = task(*args)
                future.set_result(result)
            except Exception as e:
                future.set_exception(e)
            finally:
                sem.release()