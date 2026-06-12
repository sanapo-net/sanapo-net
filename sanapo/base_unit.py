# sanapo/base_unit.py
from __future__ import annotations
from time import perf_counter
from typing import TYPE_CHECKING

from sanapo.enums import UnitType, UnitStat

if TYPE_CHECKING:
    from sanapo.config import Config
    from sanapo.logger import Logger
    from sanapo.secretary import Secretary
    from sanapo.base_module import BaseModule
    from sanapo.manifest import Manifest
    from sanapo.addr import Addr
    from sanapo.protocol import Frame
    from sanapo.message_broker import MessageBroker

# TODO add "UNIT: " in logs
class BaseUnit():
    def __init__(self,
            config: Config,
            addr: Addr,
            type: UnitType,
            broker: MessageBroker,
            module_class: any,
            module_params: dict[str, any],
            logger: Logger,
            secr: Secretary | None = None,
        ) -> None:
        self._config: Config = config
        self._logger: Logger = logger
        self._secr: Secretary = secr
        self._broker: MessageBroker = broker
        self.addr: Addr = addr
        self.type: UnitType = type
        self.manifest: Manifest = None # Kernel make it

        self._module: BaseModule | None = None
        self._module_class: any = module_class
        self._module_params: dict[str, any] = module_params
        
        self.stat: UnitStat = UnitStat.CREATING

        self._needs_rebirth: bool = False
        self._module_needs_start: bool = False
        self._needs_stop: bool = False

        self._deadline: float | None = None
        self.stop_timeout: float = config.UNIT_STOP_TIMEOUT
        self.step_timeout: float = config.UNIT_STEP_TIMEOUT
        self.start_timeout:float = config.UNIT_START_TIMEOUT
        self._last_step: float = perf_counter()
        self._step_map = {
            UnitStat.STARTING: {
                UnitType.UTILITY: [0,0],
                UnitType.SIGMA: [0,1],
                UnitType.ZOMBIE: [1,0],
                UnitType.TICKABLE: [1,1],
            },
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
        self.addr_by_str: callable = self._broker.get_addr
        self.create_module()

    def __repr__(self) -> str:
        cls_name = self._module_class.__name__
        obj_id = f"0x{id(self):X}"
        t = f"<BaseUnit: addr={self.addr} type={self.type.name} module={cls_name} id={obj_id}>"
        return t

    def create_module(self) -> bool:
        """
        Instantiates a module, passing it a reference to the container (self).
        Returns True if module was created.
        """
        try:
            view = UnitModuleView(self)
        except Exception as e:
            self.stat = UnitStat.HALTED
            self._logger.err("failed to create UnitModuleView instance: {e}", e=e)
            return False
        try:
            # The module accesses everything through a single unit object.
            self._module = self._module_class(view, **self._module_params)
            self.stat = UnitStat.CREATED
            return True
        except Exception as e:
            self.stat = UnitStat.HALTED
            self._logger.err("failed to create module instance: {e}", e=e)
            return False

    def restart_module(self, force: bool = False) -> bool:
        """Full restart of the module logic within the existing unit."""
        self._logger.dbg("UNIT: restart:begin (force={force})", force=force)
        # Shutting down the old module.
        if self._module:
            try:
                if force:
                    self._module.stop() 
                    self._module = None
                else:
                    # Soft stop. Creation only after STOPPED or stop_timeout.
                    self._needs_rebirth = True
                    self.stop()
                    self.stat = UnitStat.REBIRTHING 
                    return True
            except Exception as e:
                self._logger.err("error during Module restarting: {e}", e=e)
                return False

        # Create and start new module.
        self.create_module()
        if self.stat == UnitStat.CREATED:
            self.start()
        self._logger.dbg("UNIT: restart:end (force={force})", force=force)
        return True
    
    # TODO Check returns
    def step(self) -> bool:
        now = perf_counter()
        self._last_step = now

        if self.stat == UnitStat.STARTING:
            if self._module_needs_start:
                self._logger.dbg("UNIT: Module.start()")
                res = self._module.start()
                self._module_needs_start = False
                
                # Check if the module explicitly signaled a hard boot crash execution fault
                if res is False:
                    self._deadline = None
                    self.stat = UnitStat.HALTED
                    self._logger.wrn("UNIT: Module.start() failed. Marking as halted.")
                    return False
                else:
                    self.started()
                    return True
            elif self._deadline and now >= self._deadline:
                self._deadline = None
                self.stat = UnitStat.HALTED
                self._logger.err("UNIT: Module.start() timeout breached. Marking as halted.")
                return False

        if self.stat == UnitStat.STOPPING:
            if self._needs_stop:
                self._logger.dbg("UNIT: Module.stop()")
                res = self._module.stop()
                self._needs_stop = False
                if res is not False:
                    self.stat = UnitStat.STOPPED
                    self._deadline = None
                    self._logger.dbg("UNIT: stopped")
                    return True
            if self._deadline and now >= self._deadline:
                self.stat = UnitStat.STOPPED
                self._deadline = None
                self._logger.wrn("UNIT: stopped, forced by timeout")
                return False
        
        if self.stat == UnitStat.STOPPED:
            if self._needs_rebirth:
                self._needs_rebirth = False
                self.create_module()
                self.start()
                return True # Unit is reborned
            return False # Unit is stopped
        
        if self.stat == UnitStat.DESTROYING:
            dont_work = [UnitStat.CREATED, UnitStat.STOPPED, UnitStat.DESTROYED, UnitStat.HALTED]
            if self.stat not in dont_work:
                self.stop()
            if self.stat in dont_work:
                self.stat = UnitStat.DESTROYED
                self._module_params = None
                self._step_map = None
                self._module = None
                self.manifest = None
                self._logger = None 
                self._secr = None
                self.addr = None
                return True
            else:
                return False

        rules = self._step_map.get(self.stat, {}).get(self.type)
        was_work = False
        if rules:
            if rules[0] and self._secr: self._secr._step()
            if rules[1] and self._module:
                self._module.step()
                was_work = True
        return was_work

    def start(self, timeout: float | None = None) -> None:
        if self.stat in (UnitStat.STARTING, UnitStat.WORKING):
            return
        self._logger.dbg("UNIT: start")
        self.stat = UnitStat.STARTING
        self._module_needs_start = True
        timeout = timeout if timeout else self.start_timeout
        self._deadline = perf_counter() + timeout
    
    def started(self) -> None:
        self._deadline = None
        self._logger.dbg("UNIT: started")
        self.stat = UnitStat.WORKING
    
    def sleep(self) -> None:
        self._logger.dbg("UNIT: sleep")
        self.stat = UnitStat.SLEEPING

    def wakeup(self) -> None:
        self._logger.dbg("UNIT: wakeup")
        self.stat = UnitStat.WORKING

    def stop(self, timeout: float | None = None) -> None:
        if self.stat in (UnitStat.STOPPING, UnitStat.STOPPED):
            return
        self._logger.dbg("UNIT: stop")
        self.stat = UnitStat.STOPPING
        self._needs_stop = True
        timeout = timeout or self.stop_timeout
        self._deadline = perf_counter() + timeout

    def destroy(self) -> bool:
        if self._logger and hasattr(self._logger, 'dbg'):
            self._logger.dbg("UNIT: destroy")
        self.stat = UnitStat.DESTROYING

    
    def mutate(self, new_type: UnitType) -> bool:
        """Changes unit type on the fly"""
        self._logger.dbg("UNIT: mutate to {type}", type=new_type)
        if not isinstance(new_type, UnitType):
            t = "mutate UnitType: err expected UnitType, got {type}"
            self._logger.err(t, type=type(new_type))
            return False
        if isinstance(self._module, BaseModule):
            self.type = new_type
            return True
        elif hasattr(self._module, "step") and callable(self._module):
            self.type = new_type
            t = "mutate UnitType to {new_type}, and module is not BaseModule type"
            self._logger.dbg(t, new_type=new_type)
            return True
        
    def _validate_and_set_timeouts(self,
                start_val: float | None = None,
                stop_val: float | None = None) -> None:
        """Atomic timeout validator with race-condition prevention."""
        # Calculate safety margin
        min_allowed = max(self.step_timeout, self._config.THREAD_TCT_DEFAULT) * 1.5
        
        # --- Validate START_TIMEOUT ---
        target_start = start_val if start_val is not None else self.start_timeout
        if target_start < min_allowed:
            if start_val is not None:
                t = "timeout protection: start_timeout {old}s is too low. Raised to {min_allowed}s."
                self._logger.wrn(t, old=start_val, min_allowed=min_allowed)
            target_start = min_allowed
            
        # --- Validate STOP_TIMEOUT ---
        target_stop = stop_val if stop_val is not None else self.stop_timeout
        if target_stop < min_allowed:
            if stop_val is not None:
                t = "timeout protection: stop_timeout raised from {old}s to {min_allowed}s"
                self._logger.wrn(t, old=start_val, min_allowed=min_allowed)
            target_stop = min_allowed

        self.start_timeout = target_start
        self.stop_timeout = target_stop

    def on_net_connected(self, frame: Frame) -> None:
        """System bridge to forward connection event to the user module."""
        system_name = frame.payload.get("sys_name")
        if system_name:
            if self._module and hasattr(self._module, 'on_net_connected'):
                self._logger.dbg("try call Module.on_net_connected")
                try:
                    self._module.on_net_connected(system_name)
                except Exception as e:
                    self._logger.err("user on_net_connected callback crashed: {e}", e=e)

    def on_net_disconnected(self, frame: Frame) -> None:
        """System bridge to forward disconnection event to the user module."""
        system_name = frame.payload.get("sys_name")
        if system_name:
            if self._module and hasattr(self._module, 'on_net_disconnected'):
                self._logger.dbg("try call Module.on_net_disconnected")
                try:
                    self._module.on_net_disconnected(system_name)
                except Exception as e:
                    self._logger.err("user on_net_disconnected callback crashed: {e}", e=e)



class UnitModuleView:
    """Safe API for a Module to interact with its Unit container."""
    def __init__(self, unit: BaseUnit):
        self._unit: BaseUnit = unit

        # --- Shortened Tools ---
        self.cfg: Config = unit._config
        self.log: Logger = unit._logger
        self.scr: Secretary = unit._secr
        self.addr: Addr = unit.addr

        # --- Status Control Signals ---
        self.started: callable = unit.started # Switch to WORKING
        self.sleep: callable = unit.sleep     # Switch to SLEEPING
        self.wakeup: callable = unit.wakeup   # Switch to WORKING

    # --- Read-only Properties ---
    @property
    def stat(self) -> UnitStat:
        """Current status of the unit."""
        return self._unit.stat

    @property
    def type(self) -> UnitType:
        """Execution type of the unit."""
        return self._unit.type

    @property
    def manifest(self) -> Manifest:
        """Unit passport data."""
        return self._unit.manifest

    # --- Timeouts ---
    @property
    def start_timeout(self) -> float:
        return self._unit.start_timeout

    @start_timeout.setter
    def start_timeout(self, value: float) -> None:
        """Safely injects validated start timeout into the container."""
        self._unit._validate_and_set_timeouts(start_val=value)

    @property
    def stop_timeout(self) -> float:
        return self._unit.stop_timeout

    @stop_timeout.setter
    def stop_timeout(self, value: float) -> None:
        """Safely injects validated stop timeout into the container."""
        self._unit._validate_and_set_timeouts(stop_val=value)

    @property
    def step_timeout(self) -> float:
        return self._unit.step_timeout

    @step_timeout.setter
    def step_timeout(self, value: float) -> None:
        """Adjusts the single step processing timeout execution loop."""
        self._unit.step_timeout = value

    # --- Methods ---
    def addr_by_str(self, addr_str: str) -> BaseUnit | None:
        return self._unit.addr_by_str(addr_str, create=False, find=True)

    def get_active_systems(self) -> list[str]:
        """Returns a list of all currently connected remote system names."""
        broker = self._unit._broker
        if hasattr(broker, '_federation_routes'):
            return list(broker._federation_routes.keys())
        return []

    def get_remote_units(self, system_name: str) -> list[str]:
        """Returns a list of all registered public unit names of a specific remote node."""
        broker = self._unit._broker
        prefix = f"{system_name}:"
        with broker._addr_lock:
            # Filters the local address book and returns only the unit names
            return [
                k.split(":", 1)[1] 
                for k in broker._addr_book.keys() 
                if k.startswith(prefix)
            ]
        
    def find_remote_units_by_role(self, role: str) -> list[Addr]:
        """Finds logic addresses of all remote units matching a specific role string."""
        broker = self._unit._broker
        found_addresses = []
        with broker._addr_lock:
            for addr_str, m_dict in broker._remote_manifests.items():
                # Direct string comparison bypasses any registry or enum mismatch issues
                if m_dict.get("role") == role:
                    addr_obj = broker.get_addr(addr_str, create=False, find=True)
                    if addr_obj:
                        found_addresses.append(addr_obj)
        return found_addresses

    def find_remote_units_by_tag(self, tag: str) -> list[Addr]:
        """Finds logic addresses of all remote units possessing a specific tag string."""
        broker = self._unit._broker
        found_addresses = []
        with broker._addr_lock:
            for addr_str, m_dict in broker._remote_manifests.items():
                if tag in m_dict.get("tags", []):
                    addr_obj = broker.get_addr(addr_str, create=False, find=True)
                    if addr_obj:
                        found_addresses.append(addr_obj)
        return found_addresses
