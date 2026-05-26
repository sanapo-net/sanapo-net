# sanapo/thread_manager.py
from __future__ import annotations
import threading
import queue
from time import perf_counter
from typing import TYPE_CHECKING

from sanapo.enums import UnitStat, UnitType, ThreadStat, ThreadType
from sanapo.enums import UnitSource, UnitSelection, ExecutionStrategy
from sanapo.enums import ClubAccessError, UnitMutationError

if TYPE_CHECKING:
    from sanapo.config import Config
    from sanapo.logger import Logger
    from sanapo.base_unit import BaseUnit
    from sanapo.addr import Addr


class ThreadManager:
    def __init__(self,
                config: Config,
                logger: Logger,
                name: str,
                type: ThreadType | None = None,
                tct: float | None = None,
                tct_hiber: float | None = None,
                join_margin: float | None = None,
        ) -> None:
        self._config: Config = config
        self._logger: Logger = logger
        self.name = name
        
        # Initial setup.
        self._init_type: ThreadType = type or ThreadType.EVENT_DRIVEN
        self.type: ThreadType = self._init_type
        
        # Status.
        self.stat: ThreadStat = ThreadStat.CREATED

        # Flags from config.
        self._fps_mode = config.FPS_MODE
        self._want_hibernate_mode = config.HIBERNATE_MODE
        
        # Logic state.
        self._want_be_event_driven = True
        if self._fps_mode:
            self._want_be_event_driven = False
            self.type = ThreadType.TICKABLE

        # Timing.
        self.last_step = perf_counter()
        self.step_timeout = self._config.THREAD_STEP_TIMEOUT_DEFAULT
        self._join_margin = max(0.001, join_margin or config.THREAD_JOIN_MARGIN)
        self._tct = max(0.001, tct or config.THREAD_TCT_DEFAULT)
        # Hibernate TCT: must be longer or equal to normal TCT.
        self._tct_hibernate = max(self._tct, (tct_hiber or config.THREAD_TCT_HIBERNATE_DEFAULT))

        # Internal.
        self._units: dict[Addr, BaseUnit] = {}
        self._thread: threading.Thread | None = None
        self._init_units: dict[Addr, BaseUnit] = {}
        self._wakeup_event = threading.Event()
        self._stop_event = threading.Event()
        self._cmd_queue = queue.Queue()
        self.fps = 0

    def add_unit(self, unit: BaseUnit) -> bool:
        """Adds unit with strict thread rules."""
        # If unit already is in thread.
        if unit.addr in self._units:
            self._logger.wrn("Addetion unit: {addr} already in thread. Skipping", addr=unit.addr)
            return False
    
        is_living = unit.type in [UnitType.TICKABLE, UnitType.SIGMA]
        
        # If Addition SIGMA/TICKABLE to only ZOMBIE/UTILITY thread.
        if self._init_type == ThreadType.ONLY_EVENT_DRIVEN and is_living:
            raise ClubAccessError(
                f"Thread '{self.name}' for ZOMBIE/UTILITY only, but "
                f"there was an attempt to add unit '{unit.addr}' ({unit.type.name})"
            )
        # If Addition SIGMA/TICKABLE to for ZOMBIE/UTILITY thread.
        if self.type == ThreadType.EVENT_DRIVEN and is_living:
            t = "Guest '{addr}' (Tickable) is entering Event-Driven Thread"
            self._logger.wrn(t, addr=unit.addr)
        
        # Addition.
        self._units[unit.addr] = unit
        if not self._thread:
            self._init_units[unit.addr] = unit
        else:
            self._cmd_queue.put(('ADD', unit))
        self._update_step_timeout()
        return True

    def remove_unit(self, addr: str) -> bool:
        if addr not in self._units:
            self._logger.wrn("Can't remove {addr}: not found", addr=addr)
            return False
        unit = self._units.pop(addr)
        self._cmd_queue.put(('REMOVE', unit))
        self._update_step_timeout()
        return True

    def start(self, start_units: bool = False) -> None:
        """Starts all units, and starts thread."""
        if self.stat != ThreadStat.RELOADING:
            self.stat = ThreadStat.STARTING
        self._stop_event.clear()
        # Create an "agent" (Runner) and give him a copy of the list of units.
        units_to_run = list(self._units.values())
        if start_units:
            for unit in units_to_run:
                self._logger.dbg("unit.start() for {name}", name=unit.addr.unit)
                unit.start()
        self._thread = threading.Thread(
            target=self._run_loop, 
            args=(units_to_run,), 
            name=self.name,
            daemon=True
        )
        self._thread.start()
        if self.stat != ThreadStat.RELOADING:
            self.stat = ThreadStat.WORKING

    def reload(self, source: UnitSource, select: UnitSelection, action: ExecutionStrategy) -> bool:
        """Restarts the OS thread but restores each unit to its previous state."""
        last_stat = self.stat
        self.stat = ThreadStat.RELOADING
        t = "Reload initiated: {source}.{select}.{action}"
        self._logger.inf(t, source=source.name, select=select.name, action=action.name)
        
        # Take units from.
        if source == UnitSource.CURRENT:
            to_selection = list(self._init_units.values())
        elif source == UnitSource.INITIAL:
            to_selection = list(self._units.values())
        else:
            self._logger.err("Reload: unforeseen source: {source}", source=source)
            self.stat = last_stat
            return False
        
        select_filter_map = {
            UnitSelection.ALL: list(UnitStat),
            UnitSelection.ALIVE: list(set(UnitStat) - {UnitStat.HALTED, UnitStat.DESTROYED}),
            UnitSelection.DEAD: [UnitStat.HALTED, UnitStat.DESTROYED],
            UnitSelection.WORKING: [UnitStat.STARTING, UnitStat.WORKING,
                                    UnitStat.SLEEPING, UnitStat.REBIRTHING],
        }

        # Filter units to create in new thread.
        if select not in select_filter_map.keys():
            self._logger.err("Reload: unforeseen select: {select}", select=select)
            self.stat = last_stat
            return False
        
        to_creating = [u for u in to_selection if u in select_filter_map[select]]

        # Units to start.
        if action == ExecutionStrategy.NONE: to_start = []
        elif action == ExecutionStrategy.ALL: to_start = to_creating.copy()
        elif action == ExecutionStrategy.WORKING:
            alive = select_filter_map[UnitSelection.WORKING]
            to_start = [u for u in to_creating if u in alive]
        else:
            self._logger.err("Reload: unforeseen action: {action}", action=action)
            self.stat = last_stat
            return False

        # Stop current thread.
        if not self.join():
            self._logger.wrn("Thread join failed during reload, skipping and forcing restart")

        # Clear events for the new lifecycle.
        self._stop_event.clear()
        self._wakeup_event.clear()

        # Create and start a new OS thread.
        self._thread = threading.Thread(
            target=self._run_loop,
            args=(to_start,),
            name=self.name,
            daemon=True
        )

        self._thread.start()
        for u in to_creating: self.add_unit(u)
        self._logger.inf("Thread replayed successfully")
        self.stat = ThreadStat.WORKING
        return True

    def join(self, timeout: float | None = None) -> bool:
        """
        Orchestrates a graceful shutdown of the thread and its units.

        The method first triggers stop() for all active units. It then calculates 
        the total wait time based on the longest unit's stop_timeout plus a 
        pre-configured safety margin (THREAD_JOIN_MARGIN).

        Args:
            timeout: Optional override for the join duration. If None, it is 
                    automatically calculated from unit timeouts + margin.

        Returns:
            bool: True if the thread terminated successfully. 
                False if the thread timed out and is still alive (zombie state), 
                indicating some units failed to stop within their deadlines.
        """
        # Exit if thread dont work yet/already.
        if not self._thread or not self._thread.is_alive():
            return True
        
        if self.stat != ThreadStat.RELOADING: self.stat = ThreadStat.JOINING

        # Stop all units and cacl timeout.
        max_u_timeout = 0.0
        for unit in self._units.values():
            if unit.stat not in [UnitStat.STOPPED, UnitStat.HALTED]:
                self._logger.dbg("unit.stop() for {name}", name=unit.addr.unit)
                unit.stop()
                if unit.stop_timeout > max_u_timeout:
                    max_u_timeout = unit.stop_timeout
        if timeout is None:
            timeout = max_u_timeout + self._join_margin
        # Log timeout.
        t = "Joining. Max u_timeout: {timeout}s + margin: {margin}s"
        self._logger.inf(t, timeout=max_u_timeout, margin=self._join_margin)
        # Join process.
        self._stop_event.set()
        self.on_msg()
        self._thread.join(timeout)
        if self.stat != ThreadStat.RELOADING: self.stat = ThreadStat.JOINED
        if self._thread.is_alive():
            self._logger.err("Thread STUCK! Some units ignored stop signal")
            return False
        else:
            return True

    def _run_loop(self, units: list[BaseUnit]) -> None:
        """Main execution cycle."""
        active_units = units
        self._last_fps_calc = perf_counter()
        try:
            while not self._stop_event.is_set():
                self.last_step = start_time = perf_counter()
                tct = self._handle_commands(active_units)

                any_work_done = False
                has_tickables = False
                
                for unit in active_units:
                    # Mutation test.
                    if self._init_type == ThreadType.ONLY_EVENT_DRIVEN:
                        if unit.type in [UnitType.TICKABLE, UnitType.SIGMA]:
                            # A unit changed its type inside a closed club.
                            raise UnitMutationError(
                                f"Thread '{self.name}': Unit '{unit.addr}' mutated to "
                                f"{unit.type.name}! This is forbidden in ONLY_EVENT_DRIVEN."
                            )
                    if unit.type in [UnitType.TICKABLE, UnitType.SIGMA]:
                        has_tickables = True
                    try:
                        if unit.step(): any_work_done = True
                    except Exception as e:
                        unit.stat = UnitStat.HALTED
                        self._logger.err("Step-err in {addr}: {e}", addr=unit.addr, e=e)
                        if unit in active_units: active_units.remove(unit)
                
                self._manage_thread_type(has_tickables)
                if self._fps_mode: self._calc_fps()
                
                # TCT-managment and Event-mangment.
                execution_time = perf_counter() - start_time
                target_tct = tct
                if not any_work_done and self._want_hibernate_mode:
                    target_tct = self._tct_hibernate
                wait_time = target_tct - execution_time
                if wait_time > 0:
                    if self._wakeup_event.wait(timeout=wait_time):
                        self._wakeup_event.clear()
        except Exception as e:
            self.stat = ThreadStat.HALTED
            self._logger.crt("THREAD CRIMINAL CRASH inside _run_loop: {e}", e=e)
                    

    def _handle_commands(self, active_units: list[BaseUnit]) -> float:
        """Process ADD/REMOVE/SET_TCT commands from the queue."""
        try:
            while not self._cmd_queue.empty():
                cmd, val = self._cmd_queue.get_nowait()
                
                if cmd == 'ADD': 
                    active_units.append(val)
                
                elif cmd == 'REMOVE':
                    if val in active_units:
                        active_units.remove(val)
                
                elif cmd == 'SET_TCT':
                    # Update local variable and class attribute.
                    self._tct = val
                    return val
                    
        except Exception as e:
            self._logger.err("Command processing error: {e}", e=e)
        return self._tct

    def _update_step_timeout(self) -> None:
        """Recalculation of the time limit for one step (cycle) of the flow."""
        units = [u for u in self._units.values() if u.stat == UnitStat.WORKING]
        n = len(units)
        if n == 0:
            self.step_timeout = self._config.THREAD_STEP_TIMEOUT_DEFAULT
            return

        # Engineering attenuation coefficient.
        k = 0.3 + 0.7 * (0.8 ** (n - 1))
        
        sum_timeouts = sum(u.step_timeout for u in units)
        max_u_timeout = max(u.step_timeout for u in units)
        
        # The limit cannot be less than the longest unit + margin.
        calculated = sum_timeouts * k
        self.step_timeout = max(calculated, max_u_timeout) + self._join_margin

    def _manage_thread_type(self, has_tickables: bool) -> None:
        """Adjust type based on unit composition."""
        if has_tickables and self.type != ThreadType.TICKABLE:
            # A 'Living' unit entered a 'Lamp' club - uncomfortable but allowed.
            self.type = ThreadType.TICKABLE
            self._logger.wrn("Tickable unit detected! Switching to TICKABLE mode")
        
        elif not has_tickables and self._want_be_event_driven and self.type != self._init_type:
            # All guests left, return to original club rules.
            self.type = self._init_type
            self._logger.inf("No tickables left. Returning to {name}", name=self._init_type.name)

    def _calc_fps(self) -> None:
        """Calculate cycles per second (FPS)."""
        self._cycles += 1
        now = perf_counter()
        delta = now - self._last_fps_calc
        if delta >= 1.0:
            # Update public FPS value.
            self.fps = int(self._cycles / delta)
            # Reset counters for the next second.
            self._cycles = 0
            self._last_fps_calc = now

    @property
    def can_be_awakened(self) -> bool:
        """Checks if the thread can be woken up by a lamp signal."""
        return self.type != ThreadType.TICKABLE or self._want_hibernate_mode

    def on_msg(self) -> None:
        """Signal from Kernel: a message has arrived for a unit in this thread."""
        self._wakeup_event.set()

    def set_tct(self, new_tct: float) -> None:
        """Method for dynamically changing TCT without resetting the thread."""
        self.tct = new_tct
        self._cmd_queue.put(('SET_TCT', new_tct))

    def get_tct(self) -> float:
        return self.tct
