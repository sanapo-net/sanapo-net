from __future__ import annotations
import queue
import uuid
import os
import json
from time import perf_counter, sleep

from sanapo.addr import Addr
from sanapo.config import Config
from sanapo.logger import Logger
from sanapo.thread_manager import ThreadManager
from sanapo.message_broker import MessageBroker
from sanapo.kernel_secretary import KernelSecretary
from sanapo.watch_dog import WatchDog
from sanapo.secretary import Secretary
from sanapo.base_unit import BaseUnit
from sanapo.manifest import Manifest
from sanapo.protocol import Frame
from sanapo.tier import Tier
from sanapo.transport.adapters.queue import QueueAdapterTransport
from sanapo.enums import ThreadStat, UnitType, EnumRegistry, TierTask

class Kernel:
    """Central Orchestrator of the sanapo framework."""
    def __init__(self, enum_reg: EnumRegistry):
        self._cfg: Config = Config()
        self._addr: Addr = Addr(self._cfg.ADDR_KERNEL_STR)
        self._log: Logger = Logger(self._addr, self._cfg)
        self._reg = enum_reg

        # Infrastructure
        self._broker = MessageBroker(self._cfg, self._log, enum_reg)
        self._inbox = queue.Queue()
        self._secr = KernelSecretary(self, self._broker)
        self._watchdog = WatchDog(self, self._cfg)

        # Recipes
        self._recipes_units: dict[Addr, dict] = {}
        self._recipes_threads: dict[str, dict] = {}
        self._recipes_tiers: dict[int, dict] = {}

        # Runtime Objects
        self._units: dict[Addr, BaseUnit] = {}
        self._threads: dict[str, ThreadManager] = {}
        self._tiers: dict[int, Tier] = {}
        
        # Consistency & State
        self._dump_pending: bool = False
        self._last_sys_consist: float = 0.0
        self._is_running: bool = False
        self._is_shutting_down: bool = False

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

    def add_threads(self, configs: list[dict[str, any]]) -> dict[ThreadManager]:
        res = {}
        for cfg in configs:
            name = cfg["name"]
            if name not in self._threads:
                thread = ThreadManager(self._cfg, **cfg)
                self._threads[name] = thread
                self._recipes_threads[name] = cfg
                res[name] = thread
        self._sys_consist_changed()
        return res

    def add_tiers(self, configs: list[dict[str, any]]) -> dict[Tier]:
        res = {}
        for cfg in configs:
            num = cfg["layer_num"]
            if num not in self._tiers:
                tier = Tier(self, num, name=cfg.get("name"))
                self._tiers[num] = tier
                res[tier.name] = tier
                self._recipes_tiers[num] = cfg
        self._sys_consist_changed()
        return res

    def add_units(self, configs: list[dict[str, any]]) -> dict[str, BaseUnit]:
        res = {}
        for cfg in configs:
            unit = self._assemble_unit(cfg)
            addr = unit.addr
            self._units[addr] = unit
            self._recipes_units[addr] = cfg

            # Distribution
            th_name = cfg.get("thread", "DEFAULT")
            if th_name in self._threads:
                self._threads[th_name].add_unit(unit)
            
            tier_name = cfg["tier"]
            if tier_name in self._tiers:
                self._tiers[tier_name]._units.append(unit)

            # Routing
            self._broker.register_local_route(str(addr.unit), 
                                              QueueAdapterTransport(addr, unit.secr._inbox))
            res[unit.addr.unit] = unit

        if unit.manifest.is_persistent:
            self._sys_consist_changed()
        return res

    def _assemble_unit(self, cfg: dict) -> BaseUnit:
        """Unit factory: from recipe to living object"""
        name = cfg["name"]
        addr = self._broker.get_addr(name)
        secr = Secretary(
            address=addr,
            outbox=self._broker.bus,
            inbox=queue.Queue(),
            config=self._cfg,
            logger=Logger(f"SECR_{name}", self._cfg),
            enum_reg=self._reg,
            broker=self._broker
        )
        unit = BaseUnit(
            config=self._cfg,
            addr=addr,
            type=cfg.get("u_type", UnitType.TICKABLE),
            module_class=cfg["m_class"],
            module_params=cfg.get("m_params", {}),
            logger=Logger(f"UNIT_{name}", self._cfg),
            secr=secr
        )
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
        secr._set_unit(unit)
        return unit

    # --- Lifecycle Controls ---

    def start(self):
        """Starts all managers and initiates tier ignition"""
        self._log.inf("Ignition sequence started")
        for mgr in self._threads.values():
            if mgr.stat == ThreadStat.CREATED: mgr.start()

        for num in sorted(self._tiers.keys()):
            tier = self._tiers[num]
            tier.task = TierTask.STARTING
            tier._target_units = list(tier._units)
            # Tier timing will be initialized in Tier.step() or here
        self._is_running = True

    def loop(self):
        """Main conductor loop"""
        while self._is_running:
            start_ts = perf_counter()
            
            self._broker.step() # Route messages
            self._secr._step()  # Process self commands
            for tier in self._tiers.values(): tier.step() # Tier state machine
            self._watchdog.inspect() # Health check
            self._sys_consist_check() # Persistence check
            
            # CPU relax
            wait = self._cfg.KERNEL_TCT - (perf_counter() - start_ts)
            if wait > 0: sleep(wait)

    def rebuild_unit(self, unit: BaseUnit):
        """Destroys and recreates a unit from its recipe"""
        addr = unit.addr
        recipe = self._recipes_units.get(addr)
        if not recipe: return
        unit.destroy()
        new_unit = self._assemble_unit(recipe)
        self._units[addr] = new_unit

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
            self._log.crt(f"Atomic save failed: {e}")

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

            self._log.inf(f"Restoring system from {target}...")

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

            self._log.inf(f"System state restored from {target}")
            return True

        except Exception as e:
            self._log.crt(f"Failed to load dump {target}: {e}")
            # If main failed, try to call load again to pick up backup
            if target == main_file and os.path.exists(bak_file):
                self._log.err("Main dump corrupted, trying backup...")
                os.remove(main_file) # Remove corrupted file
                return self._sys_consist_load()
            return False

    # --- Callbacks for Tier/WatchDog ---

    def get_managers(self) -> dict[str, ThreadManager]:
        return self._threads

    def on_progress(self, text, ready, total):
        self._log.inf(f"BOOT: {text} [{ready}/{total}]")

    def handle_new_federation(self, remote_sys: str):
        self._log.inf(f"Federation: System {remote_sys} connected. Ready for unit exchange.")

    def register_remote_unit(manifest_data):
        pass

    def rebuild_unit(self, unit: BaseUnit) -> None:
        pass

    def get_manager_by_unit(unit: BaseUnit) -> ThreadManager:
        pass


    def on_thread_stuck(self, manager: ThreadManager, delay: float):
        self._log.crt(f"WatchDog: Thread {manager.name} STUCK for {delay:.2f}s!")

    def on_unit_stuck(self, unit: BaseUnit, u_delay: float, manager: ThreadManager):
        self._log.wrn(f"WatchDog: Unit {unit.addr} STUCK for {u_delay:.2f}s in {manager.name}")


    def on_tier_started(self, tier: Tier):
        self._log.inf(f"Kernel: Tier {tier.name} started successfully.")

    def on_tier_stopped(self, tier: Tier) -> None:
        pass

    def on_tier_start_fail(self, tier: Tier, problem_units: list[BaseUnit]) -> None:
        pass

    def on_tier_stop_fail(self, tier: Tier, problem_units: list[BaseUnit]) -> None:
        pass


