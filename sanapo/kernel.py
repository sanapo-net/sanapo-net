# sanapo/kernel.py
from __future__ import annotations
import uuid
import os
import json
from queue import Queue
from time import perf_counter, sleep

from sanapo.addr import Addr
from sanapo.config import Config
from sanapo.logger import Logger
from sanapo.thread_manager import ThreadManager
from sanapo.message_broker import MessageBroker
from sanapo.kernel_secretary import KernelSecretary
from sanapo.watch_dog import WatchDog
from sanapo.boot_master import BootMaster
from sanapo.translator import Translator
from sanapo.secretary import Secretary
from sanapo.base_unit import BaseUnit
from sanapo.manifest import Manifest
from sanapo.protocol import Frame
from sanapo.tier import Tier
from sanapo.views import KernelTierView, KernelBootMasterView, KernelUserView
from sanapo.transport.adapters.queue import QueueAdapterTransport
from sanapo.enums import UnitType, EnumRegistry, ThreadType

class Kernel:
    """Central Orchestrator of the sanapo framework."""
    def __init__(self, enum_reg: EnumRegistry):
        # Recipes
        self._recipes_units: dict[Addr, dict] = {}
        self._recipes_threads: dict[str, dict] = {}
        self._recipes_tiers: dict[int, dict] = {}

        # Runtime Objects
        self._units: dict[Addr, BaseUnit] = {}
        self._threads: dict[str, ThreadManager] = {}
        self._tiers: dict[int, Tier] = {}
        self._tiers_by_name: dict[str, Tier] = {}
        self._last_tier_num: int = 0
        
        # Consistency & State
        self._dump_pending: bool = False
        self._last_sys_consist: float = 0.0
        self._is_running: bool = False
        self._is_shutdowning: bool = False
        self._is_rebooting: bool = False

        # Booting
        self._boot_tier_idx = 0        # tier layer_num for start
        self._boot_global_attempt = 1  # trying of app
        self._boot_tier_attempt = 1    # triyng of tier

        # Infrastructure
        self._reg = enum_reg
        self._cfg: Config = Config()
        self._addr: Addr = Addr(self._cfg.ADDR_KERNEL_STR)
        self._log: Logger = Logger(self._addr, self._cfg)
        self._translator: Translator = Translator(self._cfg, self._log)
        self._log.set_translator(self._translator)
        self._inbox: Queue = Queue()
        self._watchdog: WatchDog = WatchDog(self, self._cfg)
        self._boot_master: BootMaster = BootMaster(KernelBootMasterView(self))
        self._broker: MessageBroker = MessageBroker(self._cfg, self._log, enum_reg)
        self._secr: KernelSecretary = KernelSecretary(self, self._broker)

        # Views
        self.tier_view = KernelTierView(self)

    # --- System Configuration (Registration) ---

    def setup(self, threads: list[dict[str, any]] = None, 
                    tiers:   list[dict[str, any]] = None,
                    units:   list[dict[str, any]] = None) -> dict[str, dict[str, any]]:
        """Unified entry for system building"""
        res = {"threads":{}, "tiers": {}, "units": {}}
        if threads:
            res["threads"] = self.add_threads(threads)
        if tiers:
            res["riers"] = self.add_tiers(tiers)
        if units:
            res["units"] = self.add_units(units)
        return res

    def add_thread(self, name: str,
                type: ThreadType | None = None,
                tct: float | None = None,
                tct_hiber: float | None = None,
                join_margin: float | None = None,) -> ThreadManager | None:
        params = locals()
        del params['self']
        filtered_params = {k: v for k, v in params.items() if v is not None}
        try:
            name = filtered_params.get('name')
            if not name:
                name = "UNKNOW"
                self._log.err("Creating ThreadManager with out name")
            addr = f"THREAD_{name}"
            logger = Logger(addr, self._cfg, self._translator)
            thread = ThreadManager(self._cfg, logger, **filtered_params)
            self._threads[name] = thread
            self._recipes_threads[name] = filtered_params
        except (TypeError, ValueError, AttributeError) as e:
            self._log.err("Creating Thread err, name={n}: {e}", n=name, e=e)
            self._log.dbg("Parameters that caused the error: {params}", params=filtered_params)
            thread = None
        return thread

    def add_threads(self, configs: list[dict[str, any]]) -> dict[ThreadManager]:
        res = {}
        for cfg in configs:
            name = cfg["name"]
            if name not in self._threads:
                thread = self.add_thread(**cfg)
                if thread:
                    res[name] = thread
        self._sys_consist_changed()
        return res

    def add_tier(self, layer_num: int | None = None, name: str | None = None) -> Tier | None:
        """Creates a new logic layer or returns an existing one by index or name."""
        """
        [some name] - create or find and return tier with name
        LAST - find and return last tier
        NEW_CREATE - create new tier (tier.autocreated=True) and return it
        AUTO_CREATING - create new tier (tier.autocreated=True) if last tier.autocreated=False 
            or return last tier
        if name != LAST and layer_num - create or find tier with layer_num, else layer_num+1
        
        # 1. Explicit Structure Definition
        kernel.add_tier(1, "CORE")         # Tier 1: CORE
        kernel.add_tier(2, "DRIVERS")      # Tier 2: DRIVERS

        # 2. Using Navigation Commands
        kernel.add_tier(name="LAST")       # Returns DRIVERS (Tier #2)
        kernel.add_tier(name="NEW_CREATE") # Creates LAYER_3 (Tier #3)

        # 3. Smart Auto-Distribution (Ideal for loops)
        kernel.add_tier()                  # Creates LAYER_4 (Auto-tier)
        kernel.add_tier()                  # Returns LAYER_4 (Reuses because it is an Auto-tier)
        kernel.add_tier(name="NEW_CREATE") # Forces creation of LAYER_5

        # 4. Access by Name during Unit Registration
        # The unit will be assigned to Tier #2 automatically.
        kernel.add_unit({"name": "GPS", "tier": "DRIVERS", ...}) 

        """
        # Try to find existing tier
        if name and name not in (None, "NEW_CREATE", "AUTO_CREATE", "LAST"):
            tier = None
            if name in self._tiers_by_name:
                tier = self._tiers_by_name[name]
            if not tier and layer_num:
                tier = self._tiers.get(layer_num)
            if tier:
                self._log.inf("Tier '{name}' (num={n}) reused.", name=name, n=tier.layer_num)
                if name and layer_num and (name != tier.name or layer_num != tier.layer_num):
                    t = "Detected add_tier with wrong pair name+num! name={name} num={num})"
                    self._log.crt(t, name=name, num=layer_num)
                    t = "Details: returned tier name={name} num={num}"
                    self._log.dbg(t, name=tier.name, num=tier.layer_num)
                return tier

        # Difine flag 'autocreated'
        is_auto = name in (None, "NEW_CREATE", "AUTO_CREATE")
        
        # Difine layer_num
        if name == "LAST":
            layer_num = self._last_tier_num
            if layer_num != None:
                self._log.wrn("Detected add_tier with LAST and layer_num! num={n}", n=layer_num)
        elif layer_num is None:
            last_tier = self._tiers.get(self._last_tier_num)
            if is_auto and last_tier and last_tier.autocreated and name != "NEW_CREATE":
                layer_num = self._last_tier_num
            else:
                self._last_tier_num += 1
                layer_num = self._last_tier_num
        
        # Name + Logger
        if name in (None, "NEW_CREATE", "AUTO_CREATE"):
            name = f"LAYER_{layer_num}"
        

        # Tier creating
        try:
            logger = Logger(f"TIER_{name}", self._cfg, self._translator)
            tier = Tier(self.tier_view, logger, layer_num, name, is_auto)
            
            # Registy
            self._tiers[tier.layer_num] = tier
            self._tiers_by_name[tier.name] = tier
            
            # Save recipe
            self._recipes_tiers[layer_num] = {"layer_num": layer_num, "name": name, "auto": is_auto}
            
            self._log.inf("Tier {name} ({num}) created", name=tier.name, num=tier.layer_num)
            return tier
        except Exception as e:
            self._log.crt("Tier creation failed: {e}", e=e)
            return None

    def add_tiers(self, configs: list[dict[str, any]]) -> dict[Tier]:
        res = {}
        for cfg in configs:
            tier = self.add_tier(**cfg)
            if tier:
                res[tier.name] = tier
        self._sys_consist_changed()
        return res

    def add_unit(self,
                name: str,
                type: UnitType,
                m_class: any,
                m_params: dict[str, any] | None = None,
                manifest: dict[str, any] | None = None,
                thread_name: str | None = None,
                tier_name: str | None = None,
                tier_layer: int | None = None
            ) -> BaseUnit | None:
        params = locals()
        del params['self']
        filtered_params = {k: v for k, v in params.items() if v is not None}
        unit = self._build_unit(filtered_params)
        if not unit:
            return False
        else:
            addr = unit.addr
            
            # Thread distribution
            thread_name = thread_name or "DEFAULT"
            if thread_name not in self._threads:
                thread = self.add_thread(thread_name)
                if thread:
                    t = "Created automatically nonexistent thread {thread_name} for unit {u_name}"
                    self._log.inf(t, u_name=addr.unit, thread_name=thread_name)
                else:
                    delleting = self._destrioy_unit(unit)
                    t = "Unit {u} is created, but thread {t} is not auto-created. Unit del:{d}"
                    self._log.crt(t, u=addr.unit, t=thread_name, d=delleting)
                    return False
            self._threads[thread_name].add_unit(unit)

            # Tier distribution
            tier = self._tiers.get(tier_layer) or self._tiers_by_name.get(tier_name)
            if tier is None:
                tier = self.add_tier(tier_layer, thread_name)
                if tier:
                    t = "Created automatically nonexistent tier {t} for unit {u}"
                    self._log.inf(t, u=addr.unit, t=f"{tier_name}|{tier_layer}")
                else:
                    delleting = self._destrioy_unit(unit)
                    t = "Unit {u} is created, but tier {t} is not auto-created. Unit del:{d}"
                    self._log.crt(t, u=addr.unit, t=f"{tier_name}|{tier_layer}", d=delleting)
                    return False
            tier._units.append(unit)
            
            self._units[addr] = unit
            self._recipes_units[addr] = filtered_params
            return unit

    def add_units(self, configs: list[dict[str, any]]) -> dict[str, BaseUnit]:
        res = {}
        need_dump = False

        for cfg in configs:
            unit = self.add_unit(**cfg)
            if not unit: continue

            # Routing
            transport = QueueAdapterTransport(unit.addr, unit.secr._inbox)
            self._broker.register_local_route(transport)
            res[unit.addr.unit] = unit

        if unit.manifest and unit.manifest.is_persistent:
            need_dump = True
        
        if need_dump:
            self._sys_consist_changed()
        return res

    def _build_unit(self, cfg: dict) -> BaseUnit | None:
        """Unit factory: from recipe to living object"""
        name = cfg["name"]
        # Addr.
        addr = self._broker.create_addr(name)
        if not addr:
            self._log.err("Unit not assembled. Didn't get Addr. (Name={n})", n=name)
            return None
        # Logger.
        try:
            logger = Logger(name, self._cfg, self._translator)
        except (TypeError, ValueError, AttributeError) as e:
            self._log.err("Unit not assembled. Didn't get Logger (Name={n}): {e}", n=name, e=e)
            return None
        # Secretary.
        try:
            secr = Secretary(
                address=addr,
                outbox=self._broker.bus,
                inbox=Queue(),
                config=self._cfg,
                logger=logger,
                evt_class=self._reg.evt,
                cmd_class=self._reg.cmd,
                resurrect_func=self.resurrect_frame
            )
        except (TypeError, ValueError, AttributeError) as e:
            self._log.err("Unit not assembled. Didn't get Secretary (Name={n}): {e}", n=name, e=e)
            return None
        # BaseUnit.
        try:
            unit = BaseUnit(
                config=self._cfg,
                addr=addr,
                type=cfg.get("u_type", UnitType.TICKABLE),
                module_class=cfg["m_class"],
                module_params=cfg.get("m_params", {}),
                logger=logger,
                secr=secr
            )
        except (TypeError, ValueError, AttributeError) as e:
            self._log.err("Unit not assembled. Didn't get BaseUnit (Name={n}): {e}", n=name, e=e)
            self._log.dbg("Details: class={c}, args={p}", c=cfg["m_class"],p=cfg.get("m_params",{}))
            return None
        # Manifest.
        param_mnfst = cfg.get("manifest", {})
        module_mnfst = unit._module.define_manifest() if unit._module else {}
        m_data = {
            "version": "1.0.0",
            "role": "default",
            "is_public": False,
            "is_persistent": True,
            **module_mnfst, 
            **param_mnfst
        }
        try:
            unit.manifest = Manifest(
                uid=str(uuid.uuid4()),
                sid=self._cfg.SYSTEM_NAME,
                addr=addr,
                version=m_data["version"],
                role=m_data["role"],
                is_public=m_data["is_public"],
                is_persistent=m_data["is_persistent"],
                tags=set(module_mnfst.get("tags", [])) | set(param_mnfst.get("tags", []))
            )
        except (TypeError, ValueError, AttributeError) as e:
            self._log.err("Unit not assembled. Didn't get Manifest (Name={n}): {e}", n=name, e=e)
            t = "Details: param_m={p}, module_m={m} final_m={f}"
            self._log.dbg(t, p=param_mnfst, m=module_mnfst, f=m_data)
            return None
        secr._set_unit(unit)
        return unit

    def _destrioy_unit(self, unit: BaseUnit) -> None:
        name = unit.addr.unit
        destroyed = unit.destroy()
        if not destroyed:
            self._log.wrn("Destroy Unit {n} without waiting", n=name)
        self._broker.deregister_addr(unit)

    def rebuild_unit(self, unit: BaseUnit):
        """Destroys and recreates a unit from its recipe"""
        addr = unit.addr
        recipe = self._recipes_units.get(addr)
        if not recipe: return
        unit.destroy()
        new_unit = self._build_unit(recipe)
        self._units[addr] = new_unit
        self._log.inf("Unit {name} was rebuiled", name=unit.addr.unit)
    
    # --- Delletions ---

    def del_unit(self, addr: Addr | str) -> bool:
        """
        Gracefully stops and removes a unit from all registries.
        Returns True if the removal process was initiated, False if not found.
        """
        # 1. Resolve address using our new 'find_addr'
        target_addr = self._broker.find_addr(addr) if isinstance(addr, str) else addr
        unit = self._units.get(target_addr)
        
        if not unit:
            self._log.wrn("Removal failed: Unit {a} not found.", a=addr)
            return False

        # 2. Signal the unit to stop (V1: no deadline waiting here)
        unit.stop()

        # 3. Remove from Thread Manager
        manager = self.get_manager_by_unit(unit)
        if manager:
            manager.remove_unit(str(target_addr.unit))

        # 4. Remove from its Tier
        for tier in self._tiers.values():
            if unit in tier._units:
                tier._units.remove(unit)

        # 5. Final cleanup in Kernel and Broker
        self._destrioy_unit(unit) # Calls unit.destroy() and broker.deregister_addr
        self._units.pop(target_addr, None)
        self._recipes_units.pop(target_addr, None)

        self._log.inf("Unit {n} removed from system.", n=target_addr.unit)
        self._sys_consist_changed()
        return True

    def del_tier(self, layer_num: int | None = None, name: str | None = None) -> bool:
        """
        Removes a Tier only if it contains no units.
        Returns True on success, False if tier is not empty or not found.
        """
        tier = self._tiers.get(layer_num) or self._tiers_by_name.get(name)
        
        if not tier:
            self._log.wrn("Removal failed: Tier {n}|{l} not found.", n=name, l=layer_num)
            return False

        if tier._units:
            self._log.err("Cannot delete Tier {n}: it is not empty!", n=tier.name)
            return False

        # Remove from all internal indexes
        self._tiers.pop(tier.layer_num, None)
        self._tiers_by_name.pop(tier.name, None)
        self._recipes_tiers.pop(tier.layer_num, None)
        
        self._log.inf("Tier {n} (Layer {l}) deleted.", n=tier.name, l=tier.layer_num)
        self._sys_consist_changed()
        return True

    def del_thread(self, name: str) -> bool:
        """
        Stops and removes a ThreadManager only if no units are assigned to it.
        Returns True on success, False if busy or not found.
        """
        manager = self._threads.get(name)
        
        if not manager:
            self._log.wrn("Removal failed: Thread {n} not found.", n=name)
            return False

        if manager._units:
            self._log.err("Cannot delete Thread {n}: units are still assigned!", n=name)
            return False

        try:
            # Shutdown the OS thread before removing the manager
            manager.join(timeout=1.0) 
            
            self._threads.pop(name)
            self._recipes_threads.pop(name, None)
            
            self._log.inf("Thread Manager {n} stopped and removed.", n=name)
            self._sys_consist_changed()
            return True
        except Exception as e:
            self._log.crt("Error deleting thread {n}: {e}", n=name, e=e)
            return False

    # --- Lifecycle Controls ---

    def restart(self) -> None:
        """Initiates global system reboot."""
        self._log.inf("BOOT: Start Rebooting")
        self._is_rebooting = True
        self.stop()

    def stop(self) -> None:
        """Starts the shutdown sequence."""
        if self._is_shutdowning: return
        self._is_shutdowning = True
        self._boot_master.shutdown()

    def start(self) -> None:
        """Starts all managers and initiates tier ignition"""
        self._log.inf("Ignition sequence started")
        self._is_running = True
        self._boot_master.ignite()

    def loop(self) -> None:
        """Main conductor loop"""
        while self._is_running:
            start_ts = perf_counter()
            
            self._broker.step() # Route messages
            self._secr._step()  # Process self commands
            for tier in self._tiers.values(): tier.step() # Tier state machine
            self._boot_master.step() # Load/Shutdown logic checking 
            self._watchdog.inspect() # Health check
            self._sys_consist_check() # Persistence check
            
            # CPU relax
            wait = self._cfg.KERNEL_TCT - (perf_counter() - start_ts)
            if wait > 0: sleep(wait)

    # --- Consistency (Persistence) ---

    def _sys_consist_changed(self):
        self._dump_pending = True
        self._last_sys_consist = perf_counter()

    def _sys_consist_check(self):
        if self._dump_pending:
            if perf_counter() - self._last_sys_consist > self._cfg.SYS_CONSIST_DELAY:
                self._sys_consist_save()
                self._dump_pending = False

    def _sys_consist_save(self):
        """Dumps blueprints to disk with rotation (Atomic Save)."""
        path = self._cfg.SYS_CONSIST_PATH
        os.makedirs(path, exist_ok=True)
        
        main_file = f"{path}/consist_dump.json"
        bak_file = f"{path}/consist_dump.bak"
        tmp_file = f"{path}/consist_dump.tmp"

        # 1. Prepare data and serialize classes
        # Important: we work with a COPY of recipes to not break runtime objects
        clean_units = {}
        for addr, recipe in self._recipes_units.items():
            r_copy = recipe.copy()
            m_class = r_copy.get("m_class")
            if m_class and not isinstance(m_class, str):
                r_copy["m_class"] = f"{m_class.__module__}:{m_class.__name__}"
            clean_units[str(addr)] = r_copy

        data = {
            "threads": self._recipes_threads,
            "tiers": self._recipes_tiers,
            "units": clean_units
        }

        try:
            # 2. Write to temporary file
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, default=lambda x: str(x))
            
            # 3. Rotate files: bak <- json, json <- tmp
            if os.path.exists(main_file):
                if os.path.exists(bak_file): os.remove(bak_file)
                os.rename(main_file, bak_file)
            
            os.rename(tmp_file, main_file)
            self._log.dbg("Consistency dump updated and rotated")
            
        except Exception as e:
            self._log.crt("Atomic save failed: {e}", e=e)

    def _sys_consist_load(self) -> bool:
        """Loads system state from the last stable dump or backup."""
        path = self._cfg.SYS_CONSIST_PATH
        main_file = f"{path}/consist_dump.json"
        bak_file = f"{path}/consist_dump.bak"

        # Try main first, then backup
        target = main_file if os.path.exists(main_file) else bak_file
        
        if not os.path.exists(target):
            self._log.wrn("No consistency dumps found. Starting fresh")
            return False

        try:
            with open(target, "r", encoding="utf-8") as f:
                data = json.load(f)

            self._log.inf("Restoring system from {target}...", target=target)

            # Restore infra
            if "threads" in data: self.add_threads(list(data["threads"].values()))
            if "tiers" in data: self.add_tiers(list(data["tiers"].values()))

            # Restore units
            unit_recipes = []
            for recipe in data.get("units", {}).values():
                if isinstance(recipe.get("m_class"), str):
                    recipe["m_class"] = self._resurrect_class(recipe["m_class"])
                unit_recipes.append(recipe)

            if unit_recipes:
                self.setup(units=unit_recipes)

            self._log.inf("System state restored from {target}", target=target)
            return True

        except Exception as e:
            self._log.crt("Failed to load dump {target}: {e}", target=target, e=e)
            # If main failed, try to call load again to pick up backup
            if target == main_file and os.path.exists(bak_file):
                self._log.err("Main dump corrupted, trying backup...")
                os.remove(main_file) # Remove corrupted file
                return self._sys_consist_load()
            return False

    def _resurrect_class(self, class_str: str) -> any:
        """Dynamically loads a Python module and extracts the specified class by string path."""
        import importlib
        
        if ":" not in class_str:
            t = "Resurrect: Invalid class string format format '{s}'. Expected 'module:ClassName'"
            self._log.crt(t, s=class_str)
            raise ValueError(f"Class string must contain ':' separator: {class_str}")
        try:
            module_path, class_name = class_str.split(":")
            module = importlib.import_module(module_path)
            target_class = getattr(module, class_name)
            t = "Resurrect: Class {c} successfully loaded from {m}"
            self._log.dbg(t, c=class_name, m=module_path)
            return target_class
        except ImportError as e:
            t = "Resurrect: Cannot find or import module '{p}'. Error: {e}"
            self._log.crt(t, p=module_path, e=e)
            raise e
        except AttributeError as e:
            t = "Resurrect: Module '{p}' loaded, but Class '{c}' was not found inside! Error: {e}"
            self._log.crt(t, p=module_path, c=class_name, e=e)
            raise e


    # --- Callbacks ---

    # Callback for BootMaster
    def on_started(self) -> None:
        """System is up. Notify project callback."""
        self._is_shutdowning = False
        self._log.inf("BOOT: Started successfully")
        cb = getattr(self, 'project_on_started', None)
        if cb and callable(cb):
            try:
                cb()
            except Exception as e:
                self._log.err("User startup callback failed: {e}", e=e)

    # Callback for BootMaster
    def on_stopped(self) -> None:
        """System is down. Manage Reboot or Halt."""
        self._log.inf("BOOT: Stopped successfully")
        if self._is_rebooting:
            self._log.inf("BOOT: Initiating reboot cycle...")
            self._is_rebooting = False
            self._is_shutdowning = False
            self.start()
        else:
            cb = getattr(self, 'project_on_stopped', None)
            if cb and callable(cb):
                try:
                    cb()
                except Exception as e:
                    self._log.err("User shutdown callback failed: {e}", e=e)
            self._is_running = False

    # Callback for Tier
    def emit_boot_progress(self, text: str, ready: int, total: int):
        """Bridge method: Kernel -> BootMaster."""
        self._boot_master.update_sub_progress(text, ready, total)
    
    # Callback for Tier
    def get_manager_by_unit(self, unit: BaseUnit) -> ThreadManager:
        th_name = self._recipes_units[unit.addr].get("thread_name", "DEFAULT")
        return self._threads[th_name]
    
    # Callback for Secretary
    def resurrect_frame(self, data: dict) -> Frame:
        """
        Converts raw dictionary to a live Frame object.
        For converting dict->Frame in thread of BaseUnit in Secretary.
        """
        return Frame.from_dict(data, self._reg, self._broker)
    
    # Callback for KernelSecretary TODO
    def handle_new_federation(self, remote_sys: str):
        t = "Federation: System {sys} connected. Ready for unit exchange."
        self._log.inf(t, sys=remote_sys)
    
    # Callback for KernelSecretary TODO
    def register_remote_unit(manifest_data):
        pass
    
    # Callback for WatchDog TODO
    def get_managers(self) -> dict[str, ThreadManager]:
        return self._threads
    
    # Callback for WatchDog TODO
    def on_thread_stuck(self, manager: ThreadManager, delay: float):
        t = "WatchDog: Thread {name} STUCK for {delay:.2f}s!"
        self._log.crt(t.format(name=manager.name, delay=delay))
    
    # Callback for WatchDog TODO
    def on_unit_stuck(self, unit: BaseUnit, u_delay: float, manager: ThreadManager):
        t = "WatchDog: Unit {addr} STUCK for {delay:.2f}s in {name}"
        self._log.wrn(t, addr=unit.addr, delay=u_delay, name=manager.name)

