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
    from sanapo.addr import Addr

# TODO in v2: don't keep units in dicts and lists, keep and manipulate Addr
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
        self._target_units: dict[Addr, BaseUnit] = []
        self.task = TierTask.NONE
        
        self.last_result_ok: bool = True
        self.problem_units: list[BaseUnit] = []

        self._unit_start_times: dict[str, float] = {}
        self._attempts: dict[str, int] = {}

    def start(self) -> bool:
        if self.task != TierTask.NONE:
            return False
        else:
            self._logger.dbg("START")
            self.task = TierTask.STARTING
            self._target_units = {unit.addr: unit for unit in self._units}
            now = perf_counter()
            for unit in self._target_units.values():
                self._unit_start_times[unit.addr] = now
                self._attempts[unit.addr] = 0
                self._logger.dbg("unit.start() for unit {name}", name=unit.addr.unit)
                unit.start()
            return True
        
    def stop(self) -> bool:
        if self.task != TierTask.NONE:
            return False
        else:
            self._logger.dbg("STOP")
            self.task = TierTask.STOPPING
            self._target_units = {unit.addr: unit for unit in self._units}
            now = perf_counter()
            for unit in self._target_units.values():
                self._unit_start_times[unit.addr] = now
                self._logger.dbg("unit.stop() for unit {name}", name=unit.addr.unit)
                unit.stop()
            return True

    def step(self) -> None:
        """Main kernel loop iteration driving tier lifecycle completion rules."""
        if self.task == TierTask.NONE:
            return

        # Safe intercept block: if there are no units registered, complete instantly
        if not getattr(self, '_target_units', []):
            is_start = (self.task == TierTask.STARTING)
            self.task = TierTask.NONE
            self._check_completion(is_start=is_start)
            return

        if self.task == TierTask.STARTING:
            self._process_starting(perf_counter())
        elif self.task == TierTask.STOPPING:
            self._process_stopping(perf_counter())

    # TODO in v2: kill zombie process and data
    def _esc_module_reborn(self, unit: BaseUnit, addr: Addr, now: float):
        """Attempt 1: Unit restarts Module via its assigned thread queue context."""
        self._logger.wrn("Reborn Module {name} via thread queue channel", name=addr.unit)
        thread = self.view.get_manager(addr)
        if thread:
            thread.reborn_module(unit)
        else:
            self._logger.err("Cant get ThreadManager for unit {name}", name=addr.unit)

        self._attempts[addr] = 1
        self._unit_start_times[addr] = now
        self.view.emit_progress(f"Reborn Module:{self.name}: {addr.unit}", *self._get_nums())

    # TODO in v2: kill zombie process and data
    def _esc_unit_rebuild(self, unit: BaseUnit, addr: Addr, now: float):
        """Attempt 2: Kernel rebuilds unit."""
        self._logger.wrn("Rebuild Unit {name} via thread queue channel", name=addr.unit)
        self.view.rebuild_unit(unit, addr) 
        self._attempts[addr] = 2
        self._unit_start_times[addr] = now
        self.view.emit_progress(f"Rebuild Unit:{self.name}: {addr.unit}", *self._get_nums())
    
    # TODO in v2: kill zombie process and data
    def _esc_thread_reload(self, unit: BaseUnit, addr: Addr, now: float):
        """Attempt 3: Replay the thread."""
        thread = self.view.get_manager(addr)
        thr = thread.name
        unt = addr.unit
        self._logger.wrn("PreRELOAD Thread {thr} (for unit {unt})", thr=thr, unt=unt)
        # Check for 'living' units from other tiers.
        others = [u for u in thread._units.values() if u != unit]
        is_safe = True
        not_alive = [UnitStat.STOPPED, UnitStat.HALTED, UnitStat.DESTROYED]
        for u in others:
            if u not in self._units and u.stat not in not_alive:
                is_safe = False
                break

        if is_safe:
            self._logger.wrn("RELOAD Thread {thr} (for unit {unt})", thr=thr, unt=unt)
            thread.reload(UnitSource.CURRENT, UnitSelection.ALL, ExecutionStrategy.ALL)
            self._attempts[addr] = 3
            self._unit_start_times[addr] = now
        else:
            self._logger.crt("RELOAD Thread {thr} with others unit. SKIP RELOADING", thr=thr)
            self._logger.crt("Unit {name}: DEAD after all attempts", name=addr.unit)
            if unit in self._target_units:
                self._target_units.pop(unit)

    def _get_nums(self) -> int:
        """Finished units count."""
        return (len(self._units) - len(self._target_units), len(self._units))

    def _finish_unit_task(self, unit: BaseUnit, work_text: str):
        """Report success and cleanup."""
        if unit in self._target_units.values():
            self._target_units.pop(unit.addr, None)
            self.view.emit_progress(f"{work_text} {self.name}: {unit.addr}", *self._get_nums())

    def _process_starting(self, now: float):
        """Startup escalation logic."""
        for addr in list(self._target_units.keys()):
            thread = self.view.get_manager(addr)
            if not thread:
                continue
            if thread.stat in [ThreadStat.STARTING, ThreadStat.RELOADING]:
                continue
            unit = thread._units.get(addr)
            if not unit:
                continue
            if thread.stat == ThreadStat.CREATED:
                self._logger.dbg("thread.start() for {name}", name=thread.name)
                thread.start()
            elif thread.stat in [ThreadStat.JOINING, ThreadStat.JOINED, ThreadStat.RELOADING]:
                t = "Start unit into thread {name} with stat {stat}"
                self._logger.wrn(t, name=thread.name, stat=thread.stat.value)
            if unit.stat == UnitStat.WORKING:
                self._finish_unit_task(unit, "Started")
                continue
            elapsed = now - self._unit_start_times[addr]
            timeout = unit.start_timeout
            attempt = self._attempts[addr]
            if elapsed > timeout:
                if attempt == 0:
                    self._esc_module_reborn(unit, addr, now)
                elif attempt == 1:
                    self._esc_unit_rebuild(unit, addr, now)
                elif attempt == 2:
                    self._esc_thread_reload(unit, addr, now)
        self._check_completion(is_start=True)

    def _process_stopping(self, now: float):
        """Logic for checking unit shutdown progress with forced thread joins."""
        for addr in list(self._target_units.keys()):
            thread = self.view.get_manager(addr)
            if not thread:
                self._target_units.pop(addr, None)
                continue
            unit = thread._units.get(addr)
            if not unit:
                self._target_units.pop(addr, None)
                continue
            if unit.stat in self.stopped_stats:
                if thread: 
                    thread.remove_unit(addr)
                    if not getattr(thread, '_units', {}):
                        thread.join(timeout=0.1)
                self._finish_unit_task(unit, "Stopped")
                continue
            elapsed = now - self._unit_start_times[addr]
            timeout = unit.stop_timeout
            if elapsed > timeout:
                self._logger.wrn("Unit {name} stop timeout! Marking as HALTED", name=addr.unit)
                unit.stat = UnitStat.HALTED
                self._target_units.pop(addr, None)
                if thread and len(thread._units) == 1:
                    t = "Forcing thread {thr} RELOAD due to stuck unit {name}"
                    self._logger.crt(t, thr=thread.name, name=addr.unit)
                    thread.reload(UnitSource.CURRENT, UnitSelection.ALL, ExecutionStrategy.ALL)
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

