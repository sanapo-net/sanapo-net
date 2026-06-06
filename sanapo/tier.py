# sanapo/tier.py
from __future__ import annotations
from time import perf_counter
from typing import TYPE_CHECKING

from sanapo.enums import UnitStat, TierStat, ThreadStat
from sanapo.enums import UnitSource, UnitSelection, ExecutionStrategy

if TYPE_CHECKING:
    from sanapo.kernel import KernelTierView
    from sanapo.config import Config
    from sanapo.logger import Logger
    from sanapo.base_unit import BaseUnit
    from sanapo.addr import Addr

# TODO in v2: don't use last_result_ok:bool, i have problem_units:list[Addr]
# TODO in v2: don't keep units in dicts and lists, keep and manipulate Addr
class Tier:
    unit_stopped_stats = [UnitStat.STOPPED, UnitStat.HALTED, UnitStat.DESTROYED]
    
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
        self.stat = TierStat.CREATED
        
        self.last_result_ok: bool = True
        self.problem_units: list[Addr] = []

        self._unit_start_times: dict[str, float] = {}
        self._attempts: dict[str, int] = {}

        self.is_flaky: bool = False # "black_mark" is Tier was restarted by boot problems

    def __repr__(self) -> str:
        obj_id = f"id=0x{id(self):X}"
        task = f"task={self.stat.name}"
        units = f"_units={self._units}"
        is_flaky = f"flaky={int(self.is_flaky)}"
        t = f"<Tier: name={self.name} num={self.layer_num} {task} {units} {is_flaky} {obj_id}>"
        return t

    # TODO maybe i can join code from start and stop (DRY)
    def start(self) -> bool:
        if self.stat != TierStat.CREATED:
            self._logger.wrn("called start, but stat {stat}", stat=self.stat.name)
            return False
        else:
            self._logger.dbg("start")
            self.stat = TierStat.STARTING
            self._target_units = {unit.addr: unit for unit in self._units}
            self.problem_units = []
            self.last_result_ok = True
            for unit in self._target_units.values():
                self._unit_start_times[unit.addr] = perf_counter()
                self._attempts[unit.addr] = 0
                self._logger.dbg("unit.start() for unit {name}", name=unit.addr.unit)
                unit.start()
            return True
        
    def stop(self) -> bool:
        if self.stat != TierStat.WORKING:
            self._logger.wrn("called stop, but stat {task}", stat=self.stat.name)
            return False
        else:
            self._logger.dbg("stop")
            self.stat = TierStat.STOPPING
            self.problem_units = []
            self.last_result_ok = True

            # Build _target_units
            self._target_units = {}
            for unit in self._units:
                addr = unit.addr
                if not addr:
                    self._logger.err("stopping: building target units: Addr==False detected")
                    for k_addr, k_unit in list(self.view.units.items()):
                        if k_unit is unit:
                            addr = k_addr
                            if addr:
                                self._logger.err("stopping: building target units: Addr restored")
                            break
                if addr:
                    unit.addr = addr
                    self._target_units[addr] = unit

            for unit in self._target_units.values():
                self._unit_start_times[unit.addr] = perf_counter()
                self._logger.dbg("unit.stop() for unit {name}", name=unit.addr.unit)
                unit.stop()
            return True

    def step(self) -> None:
        """Main kernel loop iteration driving tier lifecycle completion rules."""
        if self.stat in [TierStat.CREATED, TierStat.STOPPED]:
            return
        if self._check_completion():
            return
        if self.stat == TierStat.STARTING:
            self._process_starting()
        elif self.stat == TierStat.STOPPING:
            self._process_stopping()

    # TODO in v2: kill zombie process and data
    def _esc_module_reborn(self, unit: BaseUnit, addr: Addr):
        """Attempt 1: Unit restarts Module via its assigned thread queue context."""
        self._logger.wrn("starting: reborn Module {name}", name=addr.unit)
        t = f"starting: Tier {self.name}: Unit {addr.unit}: reborn Module"
        self.view.emit_progress(t, *self._get_nums())
        self._attempts[addr] = 1
        thread = self.view.get_manager(addr)
        res = False
        if thread:
           res = thread.reborn_module(unit)
           self._unit_start_times[addr] = perf_counter()
        else:
            self._logger.err("cant get ThreadManager for Unit {name}", name=addr.unit)
        
        return res

    # TODO in v2: kill zombie process and data
    def _esc_unit_rebuild(self, unit: BaseUnit, addr: Addr):
        """Attempt 2: Kernel rebuilds unit."""
        self._logger.wrn("starting: rebuild Unit {name}", name=addr.unit)
        t = f"starting: Tier {self.name}: Unit {addr.unit}: rebuild Unit"
        self.view.emit_progress(t, *self._get_nums())
        self._attempts[addr] = 2
        self.view.rebuild_unit(unit, addr)
        self._unit_start_times[addr] = perf_counter()
        
    # TODO in v2: kill zombie process and data
    def _esc_thread_reload(self, unit: BaseUnit, addr: Addr):
        """Attempt 3: Replay the thread."""
        thread = self.view.get_manager(addr)
        thr = thread.name
        unt = addr.unit
        self._logger.wrn("starting: prereload Thread {thr} (for Unit {unt})", thr=thr, unt=unt)
        t = f"starting: Tier {self.name}: Unit {addr.unit}: try restart Thread"
        self.view.emit_progress(t, *self._get_nums())
        self._attempts[addr] = 3
        # Check for 'living' units from other tiers.
        others = [u for u in thread._units.values() if u != unit]
        is_safe = True
        not_alive = [UnitStat.STOPPED, UnitStat.HALTED, UnitStat.DESTROYED]
        for u in others:
            if u not in self._units and u.stat not in not_alive:
                is_safe = False
                break

        if is_safe:
            self._logger.wrn("starting: reload Thread {thr} (for Unit {unt})", thr=thr, unt=unt)
            thread.reload(UnitSource.CURRENT, UnitSelection.ALL, ExecutionStrategy.ALL)
            self._unit_start_times[addr] = perf_counter()
        else:
            self._logger.crt("starting: reload Thread {thr} with others Unit, skip reloading", thr=thr)
            self._logger.crt("starting: Unit {name}: dead after all attempts", name=addr.unit)
            if unit in self._target_units:
                self._target_units.pop(unit)
                self._unit_start_times.pop(addr)

    def _process_starting(self):
        """Startup escalation logic."""
        for addr in list(self._target_units.keys()):
            
            if addr is None:
                self._logger.err("starting: addr is None, del from target_units")
                self._target_units.pop(addr, None)
                continue
            
            thread = self.view.get_manager(addr)
            if not thread:
                self._logger.err("starting: cant get Thread by addr {a}", a=addr)
                continue
            
            unit = thread._units.get(addr)
            if not unit:
                self._logger.err("starting: cant get Unit by addr {a} from Thread", a=addr)
                self._target_units.pop(addr, None)
                continue
            
            if thread.stat == ThreadStat.CREATED:
                self._logger.dbg("starting: Thread {name}.start()", name=thread.name)
                # TODO add in boot_ui info process
                start_thread = perf_counter()
                thread.start()
                self._unit_start_times[addr] += (perf_counter() - start_thread)
            
            if thread.stat == ThreadStat.STARTING:
                continue
            
            if thread.stat in [ThreadStat.JOINING, ThreadStat.JOINED, ThreadStat.RELOADING]:
                t = "starting: start Unit {a} into Thread {th} with stat {stat}"
                self._logger.wrn(t, a=addr.unit, th=thread.name, stat=thread.stat.value)

            if unit.stat == UnitStat.WORKING:
                self._unit_finished(addr, True)
                continue
            
            elapsed = perf_counter() - self._unit_start_times[addr]
            attempt = self._attempts[addr]
            if elapsed > unit.start_timeout:
                if self.is_flaky:
                    t = "starting: Unit {u_name} start timeout: Tier {t_name} is flaky, "
                    t += "skip reborn/rebuld/restart"
                    self._logger.wrn(t, u_name=addr.unit, t_name=self.name)
                    self._unit_finished(addr, False)
                    continue
                if attempt == 0:
                    self._esc_module_reborn(unit, addr)
                elif attempt == 1:
                    self._esc_unit_rebuild(unit, addr)
                elif attempt == 2:
                    self._esc_thread_reload(unit, addr)
                else:
                    t = "Tier {name}: Unit {unit} unrecoverable"
                    self._logger.crt(t, name=self.name, unit=addr.unit)
                    self._unit_finished(addr, False, "unrecoverable")

        self._check_completion()

    def _process_stopping(self):
        """Logic for checking unit shutdown progress with forced thread joins."""
        for addr in list(self._target_units.keys()):
            
            if addr is None:
                self._logger.err("stopping: Addr in target units is None")
                self._target_units.pop(addr, None)
                continue

            thread = self.view.get_manager(addr)
            if not thread:
                self._logger.err("stopping: Thread by addr is not founded in Kernel")
                self._target_units.pop(addr, None)
                continue

            unit = thread._units.get(addr)
            if not unit:
                self._logger.err("stopping: Unit by Addr isnt founded in Thread")
                self._target_units.pop(addr, None)
                continue

            unit_stat = unit.stat # save from async
            if unit_stat in self.unit_stopped_stats:
                if thread:
                    thread.remove_unit(addr)
                    if not getattr(thread, '_units', {}):
                        # Freeze queue cleanup until the hardware OS thread completely exits RAM
                        th_name = thread.name
                        join_start = perf_counter()
                        res = thread.join()
                        self._unit_start_times[addr] += (perf_counter() - join_start)
                        if res:
                            self._logger.inf("stopping: Thread {t} joined", t=th_name)
                        else:
                            t = "stopping: Thread {t} skip joinning by timeout"
                            self._logger.wrn(t, t=th_name)
                            continue

                self._unit_finished(addr, True, f"Unit had stat {unit_stat.name}")
                continue

            elapsed = perf_counter() - self._unit_start_times[addr]
            if elapsed > unit.stop_timeout:
                t = "stopping: Unit {name} stop timeout! Marking as halted"
                self._logger.wrn(t, name=addr.unit)
                unit.stat = UnitStat.HALTED
                self._unit_finished(addr, False)
                if thread and len(thread._units) == 1:
                    t = "forcing Thread {thr} reload due to stuck Unit {name}"
                    self._logger.crt(t, thr=thread.name, name=addr.unit)
                    thread.reload(UnitSource.CURRENT, UnitSelection.ALL, ExecutionStrategy.ALL)
                    
        self._check_completion()

    def _unit_finished(self, addr: Addr, success: bool, text: str = "") -> None:
        self._target_units.pop(addr)
        if success:
            res = "ok"
        else:
            res = "fail"
            self.last_result_ok = False
            self.problem_units.append(addr)
        if self.stat == TierStat.STARTING:
            t = f"Starting: Tier {self.name}: Unit {addr.unit}: ({res}{text})"
            self.view.emit_progress(t, *self._get_nums())
        # TODO DRY or Translate
        if self.stat == TierStat.STOPPING:
            t = f"Stopping: Tier {self.name}: Unit {addr.unit}: ({res}{text})"
            self.view.emit_progress(t, *self._get_nums())

    def _check_completion(self) -> bool:
        """Finalizes the tier task and reports results to the Kernel."""
        # If no units left in target list, the tier has finished its work.
        if not self._target_units:
            if self.stat == TierStat.STARTING: self.stat = TierStat.WORKING
            if self.stat == TierStat.STOPPING: self.stat = TierStat.STOPPED
            self._attempts.clear()
            self._unit_start_times.clear()
            return True
        else:
            return False

    # --- boot ui ---

    def get_progress(self) -> float:
        """Returns 0.0 to 1.0 progress of the current task."""
        if not self._units: 
            return 1.0
        
        # Count how many units are already in the required status
        if self.stat == TierStat.STARTING:
            ready = sum(1 for u in self._units if u.stat == UnitStat.WORKING)
        elif self.stat == TierStat.STOPPING:
            ready = sum(1 for u in self._units if u.stat in self.unit_stopped_stats)
        else:
            return 1.0
            
        return ready / len(self._units)

    def _get_nums(self) -> int:
        """Finished units count."""
        return (len(self._units) - len(self._target_units), len(self._units))
    