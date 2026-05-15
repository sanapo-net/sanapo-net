# sanapo/tier.py
from __future__ import annotations
from time import perf_counter
from typing import TYPE_CHECKING

from sanapo.enums import UnitStat, TierTask, ThreadStat
from sanapo.enums import UnitSource, UnitSelection, ExecutionStrategy

if TYPE_CHECKING:
    from sanapo.kernel import KernelTierView
    from sanapo.config import Config
    from sanapo.logger import Logger
    from sanapo.base_unit import BaseUnit
    
class Tier:

    stopped_stats = [UnitStat.STOPPED, UnitStat.HALTED, UnitStat.DESTROYED]
    
    """Tier manages unit lifecycle layers with active survival logic."""
    def __init__(self,
                 view: KernelTierView,
                 logger: Logger,
                 layer_num: int,
                 name: str, 
                 auto: bool | None = False
            ) -> None:
        self.view: KernelTierView = view
        self.config: Config = view.cfg
        self.layer_num: int = layer_num
        self.name: str = name
        self.autocreated: bool = auto
        self._logger: Logger = logger
        
        self._units: list[BaseUnit] = [] 
        self._target_units: list[BaseUnit] = []
        self.task = TierTask.NONE
        
        self.last_result_ok: bool = True
        self.problem_units: list[BaseUnit] = []

        self._unit_start_times: dict[str, float] = {}
        self._attempts: dict[str, int] = {}

    def start(self) -> bool:
        if self.task != TierTask.NONE:
            return False
        else:
            self.task = TierTask.STARTING
            self._target_units = list(self._units)
            now = perf_counter()
            for unit in self._target_units:
                self._unit_start_times[unit.addr] = now
                self._attempts[unit.addr] = 0
            return True
        
    def stop(self) -> bool:
        if self.task != TierTask.NONE:
            return False
        else:
            self.task = TierTask.STOPPING
            self._target_units = list(self._units)
            now = perf_counter()
            for unit in self._target_units:
                self._unit_start_times[unit.addr] = now
            return True

    def step(self) -> None:
        """Main kernel loop iteration"""
        if self.task == TierTask.NONE or not self._target_units:
            return

        if self.task == TierTask.STARTING:
            self._process_starting(perf_counter())
        elif self.task == TierTask.STOPPING:
            self._process_stopping(perf_counter())

    def _process_starting(self, now: float):
        """Startup escalation logic."""
        for unit in list(self._target_units):
            thread = self.view.get_manager(unit)
            if thread.stat == ThreadStat.CREATED:
                thread.start()
            elif thread.stat in [ThreadStat.JOINING, ThreadStat.JOINED, ThreadStat.RELOADING]:
                t = "Start unit into thread {name} witj stat {stat}"
                self._logger.wrn(t, name=thread.name, stat=thread.stat.value)
            unit.start()
            if unit.stat == UnitStat.WORKING:
                self._finish_unit_task(unit, "Started")
                continue

            elapsed = now - self._unit_start_times[unit.addr]
            timeout = unit.start_timeout
            attempt = self._attempts[unit.addr]

            # Logic levels.
            if elapsed > timeout:
                if attempt == 0:
                    self._esc_reborn(unit, now)
                elif attempt == 1:
                    self._esc_rebuild(unit, now)
                elif attempt == 2:
                    self._esc_thread_replay(unit, now)
                elif attempt == 3:
                    self._esc_fail(unit)

        self._check_completion(is_start=True)

    def _esc_reborn(self, unit: BaseUnit, now: float):
        """Attempt 1: Module restart."""
        self._logger.wrn("{addr}: Slow start. Action: REBORN", addr=unit.addr)
        unit.restart_module(force=True)
        self._attempts[unit.addr] = 1
        self._unit_start_times[unit.addr] = now
        t = f"Restarting Unit:{self.name}: {unit.addr}"
        self.view.emit_progress(t, self._get_num(), len(self._units))

    def _esc_rebuild(self, unit: BaseUnit, now: float):
        """Attempt 2: Kernel rebuilds unit."""
        self._logger.err("{addr}: Reborn failed. Action: REBUILD", addr=unit.addr)
        self.view.rebuild_unit(unit) 
        self._attempts[unit.addr] = 2
        self._unit_start_times[unit.addr] = now
        t = f"Rebuilding unit:{self.name}: {unit.addr}"
        self.view.emit_progress(t, self._get_num(), len(self._units))

    def _esc_thread_replay(self, unit: BaseUnit, now: float):
        """Attempt 3: Replay the thread."""
        thread = self.view.get_manager(unit)
        # Check for 'living' units from other tiers.
        others = [u for u in thread._units.values() if u != unit]
        is_safe = True
        not_alive = [UnitStat.STOPPED, UnitStat.HALTED, UnitStat.DESTROYED]
        for u in others:
            if u not in self._units and u.stat not in not_alive:
                is_safe = False
                break

        if is_safe:
            self._logger.crt("Thread {name} STUCK. Action: REPLAY", name=thread.name)
            thread.reload(UnitSource.CURRENT, UnitSelection.ALL, ExecutionStrategy.WORKING)
            self._attempts[unit.addr] = 3
            self._unit_start_times[unit.addr] = now
        else:
            self._logger.err("Thread {name} busy with others. Action: SKIP UNIT", name=thread.name)
            self._esc_fail(unit)

    def _esc_fail(self, unit: float):
        """Final unit drop."""
        self._logger.crt("Unit {addr}: DEAD after all attempts", addr=unit.addr)
        if unit in self._target_units:
            self._target_units.remove(unit)

    def _get_num(self) -> int:
        """Finished units count."""
        return len(self._units) - len(self._target_units)

    def _finish_unit_task(self, unit: BaseUnit, work_text: str):
        """Report success and cleanup."""
        if unit in self._target_units:
            self._target_units.remove(unit)
            t = f"{work_text} {self.name}: {unit.addr}"
            self.view.emit_progress(t, self._get_num(), len(self._units))

    def _process_stopping(self, now: float):
        """Logic for checking unit shutdown progress."""
        for unit in self._target_units:
            thread = self.view.get_manager(unit)
            unit.stop()
            # Check if unit is already dead or stopped.
            if unit.stat in self.stopped_stats:
                if thread: thread.remove_unit(unit.addr)
                self._finish_unit_task(unit, "Stopped")
                continue

            elapsed = now - self._unit_start_times[unit.addr]
            timeout = unit.stop_timeout

            # If shutdown takes too long.
            if elapsed > timeout:
                t = "Unit {addr} stop timeout! Marking as HALTED."
                self._logger.wrn(t, addr=unit.addr)
                unit.stat = UnitStat.HALTED

                if unit in self._target_units:
                    self._target_units.remove(unit)
                
                # Optional: try to kill the thread if it's the only unit there.
                if thread and len(thread._units) == 1:
                    t = "Forcing thread {name} RELOAD due to stuck unit {addr}"
                    self._logger.crt(t, name=thread.name, addr=unit.addr)
                    thread.reload(UnitSource.CURRENT,  UnitSelection.ALL, ExecutionStrategy.ALL)

        self._check_completion(is_start=False)

    def _check_completion(self, is_start: bool):
        """Finalizes the tier task and reports results to the Kernel."""
        # If no units left in target list, the tier has finished its work.
        if not self._target_units:
            self.problem_units = []
            for u in self._units:
                if is_start:
                    if u.stat != UnitStat.WORKING:
                        self.problem_units.append(u)
                else:
                    if u.stat not in self.stopped_stats:
                        self.problem_units.append(u)
            # Fix results
            self.last_result_ok = (len(self.problem_units) == 0)
            # Reset tier task.
            self.task = TierTask.NONE
            self._attempts.clear()
            self._unit_start_times.clear()

    def get_progress(self) -> float:
        """Returns 0.0 to 1.0 progress of the current task."""
        if not self._units: 
            return 1.0
        
        # Count how many units are already in the required status
        if self.task == TierTask.STARTING:
            ready = sum(1 for u in self._units if u.stat == UnitStat.WORKING)
        elif self.task == TierTask.STOPPING:
            ready = sum(1 for u in self._units if u.stat in self.stopped_stats)
        else:
            return 1.0
            
        return ready / len(self._units)

