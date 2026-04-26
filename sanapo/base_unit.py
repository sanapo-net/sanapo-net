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
            config: Config,
            addr: Addr,
            type: UnitType,
            module_class: any,
            module_params: dict[str, any],
            logger: Logger,
            secr: Secretary | None = None
        ) -> None:
        self.config: Config = config
        self.addr: Addr = addr
        self.type: UnitType = type
        self.logger: Logger = logger
        self.secr: Secretary | None = secr

        self._module: BaseModule | None = None
        self._module_class: any = module_class
        self._module_params: dict[str, any] = module_params

        self.stat: UnitStat = UnitStat.CREATING

        self._stop_deadline: float | None = None
        self._is_destroying: bool = False
        self._needs_rebirth = False
        self._last_step: float = perf_counter()
        self.step_timeout = getattr(module_class, 'step_timeout', config.UNIT_STEP_TIMEOUT)
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
        self.secr.configure_subscriptions(system={
            SysType.U_START: self.start,
            SysType.U_SLEEP: self.sleep,
            SysType.U_WAKEUP: self.wakeup,
            SysType.U_STOP: self.stop,
            SysType.U_DESTROY: self.destroy,
        })

        self.create_module()
        self.stop_timeout: float = getattr(self._module, 'stop_timeout', self.config.UNIT_STOP_TIMEOUT)        


    def create_module(self):
        """Instantiates a module, passing it a reference to the container (self)."""
        try:
            # The module accesses everything through a single unit object.
            self._module = self._module_class(self, **self._module_params)
            self.stat = UnitStat.CREATED
        except Exception as e:
            self.stat = UnitStat.HALTED
            self.logger.err(f"Failed to create module instance: {e}")

    def reborn_module(self, force: bool = False):
        """Full restart of the module logic within the existing unit."""
        self.logger.inf(f"Rebirth of module in {self.addr} initiated (force={force})")

        # Shutting down the old module.
        if self._module:
            try:
                if force:
                    self._module.stop() 
                    self._module = None
                else:
                    # Soft stop. Creation only after STOPPED or stop_timeout
                    self._needs_rebirth = True
                    self.stop()
                    self.stat = UnitStat.REBIRTHING 
                    return
            except Exception as e:
                self.logger.err(f"Error during module rebirthing: {e}")

        # Create and start new module
        self.create_module()
        if self.stat == UnitStat.CREATED:
            self.start()


    def step(self) -> bool:
        now = perf_counter()
        self._last_step = now
        if self._is_destroying:
            self.destroy()
            return False

        if self.stat == UnitStat.STOPPING:
            if self._stop_deadline and now >= self._stop_deadline:
                self.stat = UnitStat.STOPPED
                self._stop_deadline = None
                self.logger.inf(f"Unit {self.addr} forced to STOPPED by timeout")
                return False
        
        if self.stat == UnitStat.STOPPED:
            if self._needs_rebirth:
                self._needs_rebirth = False
                self.create_module()
                self.start()
                return True # Unit is reborned
            return False # Unit is stopped

        rules = self._step_map.get(self.stat, {}).get(self.type)
        was_work = False
        if rules:
            if rules[0] and self.secr: self.secr.step()
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
        self.logger = None 
        self.secr = None
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
