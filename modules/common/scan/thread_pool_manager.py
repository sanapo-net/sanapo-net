# modules/common/scan/thread_pool_manager.py
from __future__ import annotations

import threading
from concurrent.futures import Future
from queue import Queue
from typing import Any, Callable


class ThreadPoolManager:
    """
    A thread pool that divides work into named categories.
    Each category has its own concurrency limit.
    """

    def __init__(self, max_workers: int) -> None:
        """
        Start a pool with a fixed total number of worker threads.

        Args:
            max_workers: Maximum OS threads allowed (must be >= 1).
        """
        if max_workers < 1:
            raise ValueError("max_workers must be at least 1")
        self._max_workers: int = max_workers
        self._pools: dict[str, threading.BoundedSemaphore] = {}
        self._task_queue: Queue = Queue()
        self._threads: list[threading.Thread] = []
        self._shutdown_flag = threading.Event()
        self._lock = threading.Lock()

        # Launch all workers immediately.
        for _ in range(self._max_workers):
            t = threading.Thread(target=self._worker, daemon=True)
            t.start()
            self._threads.append(t)

    # ------------------------------------------------------------------
    # Global worker count management
    # ------------------------------------------------------------------

    def get_max_workers(self) -> int:
        """Return the current total thread limit."""
        return self._max_workers

    def set_max_workers(self, new_limit: int) -> None:
        """
        Change the total number of worker threads.

        Args:
            new_limit: New maximum thread count (>= 1).
        """
        if new_limit < 1:
            raise ValueError("max_workers must be at least 1")
        with self._lock:
            # Remove any threads that have already stopped.
            self._cleanup_threads()

            old = self._max_workers
            if new_limit == old:
                return
            delta = new_limit - old
            self._max_workers = new_limit
            if delta > 0:
                # Start extra workers.
                for _ in range(delta):
                    t = threading.Thread(target=self._worker, daemon=True)
                    t.start()
                    self._threads.append(t)
            else:
                # Send a stop signal to the excess workers.
                # They will be cleaned up next time _cleanup_threads runs.
                for _ in range(-delta):
                    self._task_queue.put(None)

    # ------------------------------------------------------------------
    # Category management
    # ------------------------------------------------------------------

    def new_pool(self, name: str, max_concurrent: int) -> None:
        """
        Create a new category with its own concurrency limit.

        Args:
            name: Unique category name (e.g., 'SEC_05').
            max_concurrent: Max tasks that can run at the same time in this category.
        """
        with self._lock:
            if name in self._pools:
                raise ValueError(f"Pool '{name}' already exists")
            self._pools[name] = threading.BoundedSemaphore(max_concurrent)

    def close_pool(self, name: str) -> None:
        """
        Remove a category. No new tasks will be accepted;
        already running tasks finish normally.

        Args:
            name: Category to remove.
        """
        with self._lock:
            sem = self._pools.pop(name, None)
            if sem is not None:
                # Drain the semaphore to prevent new acquires.
                while sem.acquire(blocking=False):
                    pass

    def get_pool_size(self, name: str) -> int:
        """Return the concurrency limit for a category."""
        with self._lock:
            sem = self._pools.get(name)
            if sem is None:
                raise ValueError(f"Pool '{name}' does not exist")
            return sem._initial_value

    def resize_pool(self, name: str, max_concurrent: int) -> None:
        """
        Update the concurrency limit of an existing category.

        Args:
            name: Category name.
            max_concurrent: New max simultaneous tasks.
        """
        with self._lock:
            if name not in self._pools:
                raise ValueError(f"Pool '{name}' does not exist")
            self._pools[name] = threading.BoundedSemaphore(max_concurrent)

    def setup(self, config: dict[str, int]) -> None:
        """
        Add or update multiple categories in one call.

        Args:
            config: Dict mapping category name -> concurrency limit.
        """
        for name, limit in config.items():
            if name not in self._pools:
                self.new_pool(name, limit)
            else:
                self.resize_pool(name, limit)

    def available_slots(self, name: str) -> int:
        """
        Return how many free slots are left in a category.

        Args:
            name: Category name.

        Returns:
            Number of free slots (0 if the category does not exist).
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
        Hand a task to the pool. It will run when a slot is free.

        Args:
            task: The function to execute.
            args: Positional arguments for the function.
            category: The category that controls concurrency.
            ttl: Maximum lifetime in seconds (for watchdog tracking).
            timeout: Network timeout passed into the task.

        Returns:
            A Future representing the task's result.

        Raises:
            RuntimeError: If the category doesn't exist or no free slot is available.
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
        Gracefully stop all worker threads.
        Wait for running tasks to finish (up to 5 seconds each).
        """
        self._shutdown_flag.set()
        with self._lock:
            self._cleanup_threads()
        # Send a stop signal to each live thread.
        for _ in self._threads:
            self._task_queue.put(None)
        for t in self._threads:
            t.join(timeout=5)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _cleanup_threads(self) -> None:
        """Remove threads that have already finished from the internal list."""
        # Must be called while holding self._lock.
        self._threads = [t for t in self._threads if t.is_alive()]

    def _worker(self) -> None:
        """Keep taking tasks from the queue and run them."""
        while not self._shutdown_flag.is_set():
            item = self._task_queue.get()
            if item is None:          # shutdown sentinel
                break
            task, args, timeout, future, sem = item
            try:
                result = task(*args)
                future.set_result(result)
            except Exception as e:
                future.set_exception(e)
            finally:
                sem.release()