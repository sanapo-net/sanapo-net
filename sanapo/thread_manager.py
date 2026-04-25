# sanapo/thread_manager.py
from __future__ import annotations
import threading
import queue
from enum import Enum
from time import perf_counter
from typing import TYPE_CHECKING

from sanapo.enums import UnitStat, UnitType, ThreadType, ClubAccessError, UnitMutationError

if TYPE_CHECKING:
    from sanapo.config import Config
    from sanapo.logger import Logger
    from sanapo.base_unit import BaseUnit

Addr = Enum

class ThreadManager:
    def __init__(self,
                config: Config,
                name: str,
                type: ThreadType | None = None,
                margin: float | None = None,
                tct: float | None = None
        ) -> None:
        self._config = config
        self._logger = Logger("TH_" + name)
        self.name = name
        
        # Initial setup
        self._init_type = type if type else ThreadType.EVENT_DRIVEN
        self.type = self._init_type
        
        # Flags from config
        self._fps_mode = config.FPS_MODE
        self._want_hibernate_mode = config.HIBERNATE_MODE
        
        # Logic state
        self._want_be_event_driven = True
        if self._fps_mode:
            self._want_be_event_driven = False
            self.type = ThreadType.TICKABLE

        # Timing
        self._margin = margin if margin is not None else config.THREAD_JOIN_MARGIN
        self._tct = tct if tct is not None else config.THREAD_TCT_DEFAULT
        # Hibernate TCT: must be longer or equal to normal TCT
        if config.THREAD_TCT_HIBERNATE_DEFAULT > self._tct:
            self._tct_hibernate = config.THREAD_TCT_HIBERNATE_DEFAULT
        else:
            self._tct_hibernate = self._tct

        # Internal
        self._units: dict[Addr, BaseUnit] = {}
        self._init_unit: dict[Addr, BaseUnit] = {}
        self._wakeup_event = threading.Event()
        self._stop_event = threading.Event()
        self._cmd_queue = queue.Queue()
        self.fps = 0

    def add_unit(self, unit: BaseUnit) -> None:
        """Adds unit with strict thread rules."""
        is_living = unit.type in [UnitType.TICKABLE, UnitType.SIGMA]
        
        # Addtion SIGMA/TICKABLE to only ZOMBIE/UTILITY thread
        if self._init_type == ThreadType.ONLY_EVENT_DRIVEN and is_living:
            raise ClubAccessError(
                f"Thread '{self.name}' for ZOMBIE/UTILITY only, but "
                f"there was an attempt to add unit '{unit.addr}' ({unit.type.name})"
            )
        # Addtion SIGMA/TICKABLE to for ZOMBIE/UTILITY thread
        if self.type == ThreadType.EVENT_DRIVEN and is_living:
            self._logger.wrn(f"Guest '{unit.addr}' (Tickable) is entering Event-Driven Thread.")
            
        self._units[unit.addr] = unit
        if not self._thread:
            self._init_unit[unit.addr] = unit
        else:
            self._cmd_queue.put(('ADD', unit))

    def remove_unit(self, addr: str):
        if addr in self._units:
            unit = self._units.pop(addr)
            self._cmd_queue.put(('REMOVE', unit))

    def start(self):
        """Starts all units, and starts thread"""
        self._stop_event.clear()
        # Create an "agent" (Runner) and give him a copy of the list of units
        units_to_run = list(self._units.values())
        for unit in units_to_run: unit.start()
        self._thread = threading.Thread(
            target=self._run_loop, 
            args=(units_to_run,), 
            name=self.name,
            daemon=True
        )
        self._thread.start()

    def reload(self, mode: str = "current"):
        """
        Restart modes:
        'initial' - only those that existed at creation
        'current' - all current units
        'healthy' - only those that are not in HALTED status
        """
        self.join() # We gently extinguish the old flow
        if mode == "initial":
            self._units = self._init_unit.copy()
        elif mode == "current":
            self._units = self._units.copy()
        elif mode == "healthy":
            self._units = {addr: u for addr, u in self._units.items() 
                           if u.stat != UnitStat.DESTROYED}
        self.start()

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
        # Exit if thread dont work yet/already
        if not self._thread or not self._thread.is_alive():
            return True
        # Stop all units and cacl timeout
        max_u_timeout = 0.0
        for unit in self._units.values():
            if unit.stat not in [UnitStat.STOPPED, UnitStat.HALTED]:
                unit.stop()
                if unit.stop_timeout > max_u_timeout:
                    max_u_timeout = unit.stop_timeout
        if timeout is None:
            timeout = max_u_timeout + self._margin
        # Log timeout
        t = f"Joining {self.name}. Max u_timeout: {max_u_timeout}s + margin: {self._margin}s"
        self._logger.inf(t)
        # Join process
        self._stop_event.set()
        self.trigger_wakeup()
        self._thread.join(timeout)
        if self._thread.is_alive():
            self._logger.err(f"Thread {self.name} STUCK! Some units ignored stop signal.")
            return False
        else:
            return True

    # TODO Do i need auto-reboot for HALTED 
    def _run_loop(self, units: list[BaseUnit]):
        """Main execution cycle."""
        active_units = units
        self._last_fps_calc = perf_counter()
        
        while not self._stop_event.is_set():
            start_time = perf_counter()
            tct = self._handle_commands(active_units)

            any_work_done = False
            has_tickables = False
            
            for unit in active_units:
                # Mutation test
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
                    # TODO Do i need auto-reboot for HALTED 
                    unit.stat = UnitStat.HALTED
                    self._logger.err(f"Step-err in {unit.addr}: {e}")
            
            self._manage_thread_type(has_tickables)
            if self._fps_mode: self._calc_fps()
            
            # TCT-managment and Event-mangment
            execution_time = perf_counter() - start_time
            target_tct = tct
            if not any_work_done and self._want_hibernate_mode:
                target_tct = self._tct_hibernate
            wait_time = target_tct - execution_time
            if wait_time > 0:
                if self._wakeup_event.wait(timeout=wait_time):
                    self._wakeup_event.clear()

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
                    # Update local variable and class attribute
                    self._runner_tct = val
                    return val
                    
        except Exception as e:
            self._logger.err(f"Command processing error in {self.name}: {e}")
        return self._runner_tct

    def _manage_thread_type(self, has_tickables: bool):
        """Adjust type based on unit composition."""
        if has_tickables and self.type != ThreadType.TICKABLE:
            # A 'Living' unit entered a 'Lamp' club - uncomfortable but allowed
            self.type = ThreadType.TICKABLE
            t = f"Thread {self.name}: Tickable unit detected! Switching to TICKABLE mode."
            self._logger.wrn(t)
        
        elif not has_tickables and self._want_be_event_driven and self.type != self._init_type:
            # All guests left, return to original club rules
            self.type = self._init_type
            t = f"Thread {self.name}: No tickables left. Returning to {self._init_type.name}"
            self._logger.inf(t)

    def _calc_fps(self) -> None:
        """Calculate cycles per second (FPS)."""
        self._cycles += 1
        now = perf_counter()
        delta = now - self._last_fps_calc
        if delta >= 1.0:
            # Update public FPS value
            self.fps = int(self._cycles / delta)
            # Reset counters for the next second
            self._cycles = 0
            self._last_fps_calc = now

    # TODO do i need it
    @property
    def can_be_awakened(self) -> bool:
        """Checks if the thread can be woken up by a lamp signal."""
        return self.type != ThreadType.TICKABLE or self._want_hibernate_mode

    def on_msg(self):
        """Signal from Kernel: a message has arrived for a unit in this thread."""
        self._wakeup_event.set()

    def set_tct(self, new_tct: float):
        """Method for dynamically changing TCT without resetting the thread"""
        self.tct = new_tct
        self._cmd_queue.put(('SET_TCT', new_tct))

    def get_tct(self) -> float:
        return self.tct
