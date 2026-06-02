# sanapo/watch_dog.py
from __future__ import annotations
from time import perf_counter
from typing import TYPE_CHECKING

from sanapo.enums import UnitStat, ThreadStat

if TYPE_CHECKING:
    from sanapo.kernel import Kernel
    from sanapo.config import Config

class WatchDog:
    def __init__(self, kernel: Kernel, config: Config) -> None:
        self.kernel: Kernel = kernel
        self.config: Config = config
        self._last_step = 0.0
        self._suspects = set() # Streams for early verification
        self.tct = config.WATCHDOG_TCT

    def inspect(self):
        now = perf_counter()
        if now - self._last_step < self.tct:
            return
        self._last_step = now

        for manager in self.kernel.get_managers().values():
            if manager.stat != ThreadStat.WORKING:
                continue
            delay = now - manager.last_step
            # If the flow is delayed, but not yet critical.
            margin = max(self.tct * 1.5, self.tct + manager._tct_hibernate)
            if delay > manager.step_timeout - margin:
                # We give the manager a command to recheck their timeouts
                # (in case the user raised them).
                manager._update_step_timeout()

            # Final check.
            if delay > manager.step_timeout:
                self.kernel.on_thread_stuck(manager, delay)
            else:
                # Checking individual units within a live stream.
                for unit in manager._units.values():
                    if unit.stat == UnitStat.WORKING:
                        u_delay = now - unit._last_step
                        if u_delay > unit.step_timeout:
                            manager.reborn_module(unit)
