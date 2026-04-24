# sanapo/base_unit.py
from __future__ import annotations
from time import perf_counter
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sanapo.enums import UnitType, UnitStat, SysType
    from sanapo.secretary import Secretary
    from sanapo.logger import Logger
    from sanapo.base_module import BaseModule

Addr = Enum

class BaseUnit():
    def __init__(self, unit_type: UnitType, addr: Addr,
                 module: BaseModule, logger: Logger, secr: Secretary | None = None) -> None:
        self.type: UnitType = unit_type
        self.addr: Addr = addr
        self._module: BaseModule = module
        self._logger: Logger = logger
        self._secr: Secretary | None = secr
        
        self.stat: UnitStat = UnitStat.READY
        self._is_destroy: bool = False
        self._last_step: float = None
        self._stop_deadline: float | None = None
        self._step_map = {
            UnitStat.WORKING: {
                UnitType.UTILITY: [0,0],
                UnitType.SIGMA: [0,1],
                UnitType.ZOMBIE: [1,0],
                UnitType.TICKABLE: [1,1],
            },
            UnitStat.SLEEPING: {
                UnitType.UTILITY: [0,0],
                UnitType.SIGMA: [0,0],
                UnitType.ZOMBIE: [1,0],
                UnitType.TICKABLE: [1,0],
            }
        }
        self._secr.configure_subscriptions(system={
            SysType.U_START: self.start,
            SysType.U_SLEEP: self.sleep,
            SysType.U_WAKEUP: self.wakeup,
            SysType.U_STOP: self.stop,
            SysType.U_DESTROY: self.destroy,
        })

    def step(self) -> None:
        now = perf_counter()
        self._last_step = now
        if self._is_destroy: return

        if self.stat == UnitStat.STOPPING:
            if self._stop_deadline and now >= self._stop_deadline:
                self.stat = UnitStat.STOPPED
                self._logger.inf(f"Unit {self.addr} forced to STOPPED by timeout")
                return

        rules = self._step_map.get(self.stat, {}).get(self.type)
        if rules:
            if rules[0] and self._secr: self._secr.step()
            if rules[1] and self._module: self._module.step()

    def start(self) -> bool:
        self.stat = UnitStat.STARTING
        self._module.start()
        return True
    
    def sleep(self) -> bool:
        self.stat = UnitStat.SLEEPING
        return True

    def wakeup(self) -> bool:
        self.stat = UnitStat.WORKING
        return True

    def stop(self, timeout: float) -> bool:
        self.stat = UnitStat.STOPPING
        self._stop_deadline = perf_counter() + timeout
        self._module.stop()
        return True

    def destroy(self) -> bool:
        if self._is_destroy: return True
        if self.stat not in [UnitStat.STOPPED, UnitStat.HALTED]:
            self.stop(timeout=0)
            self.stat = UnitStat.STOPPED
        self._is_destroy = True
        self._step_map = None
        self._module = None
        self._logger = None 
        self._secr = None
        return True
