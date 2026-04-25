# sanapo/base_unit.py
from __future__ import annotations
from time import perf_counter
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sanapo.enums import UnitType, UnitStat, SysType
    from sanapo.config import Config
    from sanapo.logger import Logger
    from sanapo.secretary import Secretary
    from sanapo.base_module import BaseModule

Addr = Enum

class BaseUnit():
    def __init__(self,
            unit_type: UnitType,
            addr: Addr,
            config: Config,
            module: BaseModule,
            logger: Logger,
            secr: Secretary | None = None
        ) -> None:
        self.type: UnitType = unit_type
        self.addr: Addr = addr
        self.config: Config = config
        self.module: BaseModule = module
        self.logger: Logger = logger
        self.secr: Secretary | None = secr
        
        self.stat: UnitStat = UnitStat.READY
        self._is_destroying: bool = False
        self._last_step: float = None
        self._stop_deadline: float | None = None
        self.stop_timeout: float = getattr(module, 'stop_timeout', self.config.UNIT_STOP_TIMEOUT)
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

    def step(self) -> bool:
        now = perf_counter()
        self._last_step = now
        if self._is_destroying:
            self.destroy()
            return False

        if self.stat == UnitStat.STOPPING:
            if self._stop_deadline and now >= self._stop_deadline:
                self.stat = UnitStat.STOPPED
                self._logger.inf(f"Unit {self.addr} forced to STOPPED by timeout")
                return False

        rules = self._step_map.get(self.stat, {}).get(self.type)
        was_work = False
        if rules:
            if rules[0] and self._secr: self._secr.step()
            if rules[1] and self._module:
                self._module.step()
                was_work = True
        return was_work

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

    def stop(self, timeout: float | None = None) -> bool:
        timeout = timeout if timeout else self.stop_timeout
        self.stat = UnitStat.STOPPING
        self._stop_deadline = perf_counter() + timeout
        self._module.stop()
        return True

    def destroy(self) -> bool:
        if not self._is_destroying:
            self._is_destroying = True
            if self.stat not in [UnitStat.STOPPED, UnitStat.DESTROYED]:
                self.stop()
                return False
        self._step_map = None
        self._module = None
        self._logger = None 
        self._secr = None
        return True
    
    def mutate(self, new_type: UnitType) -> bool:
        if not isinstance(new_type, UnitType):
            self.logger.err(f"Change UnitType, expected UnitType, got {type(new_type)}")
            return False
        if isinstance(self._module, BaseModule):
            self.type = new_type
            return True
        elif hasattr(self._module, "step") and callable(self._module):
            self.type = new_type
            self.logger.dbg(f"Change UnitType to {new_type}, and modile is not BaseModule type")
            return True
