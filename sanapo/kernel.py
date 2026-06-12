# sanapo/kernel.py
from __future__ import annotations
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
from sanapo.views import KernelTierView, KernelBootMasterView
from sanapo.transport.adapters.queue import QueueAdapterTransport
from sanapo.enums import SysType, UnitType, EnumRegistry, ThreadType, BootTask
from sanapo.enums import UnitSource, UnitSelection, ExecutionStrategy
from sanapo.transport.services.udp import UdpBeacon, UdpListener
from sanapo.transport.services.tcp import TcpService

class Kernel:
    """Central Orchestrator of the sanapo framework."""
    def __init__(self, enum_reg: EnumRegistry, system_name: str | None = None) -> None:
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
        if system_name: self._cfg.SYSTEM_NAME = system_name
        self._addr: Addr = Addr(self._cfg.SYSTEM_NAME, self._cfg.ADDR_KERNEL_STR)
        self._inbox: Queue = Queue()
        self._log: Logger = Logger(self._addr, self._cfg)
        self._translator: Translator = Translator(self._cfg, self._log)
        self._log.set_translator(self._translator) 
        self._watchdog: WatchDog = WatchDog(self, self._cfg)
        self._boot_master: BootMaster = BootMaster(KernelBootMasterView(self))
        self._broker: MessageBroker = MessageBroker(self._cfg, self._log, enum_reg)
        self._secr: KernelSecretary = KernelSecretary(self, self._broker)

        self._tcp_service: TcpService | None = None
        self._udp_beacon: UdpBeacon | None = None
        self._udp_listener: UdpListener | None = None

        self.tier_view = KernelTierView(self)

        kernel_transport = QueueAdapterTransport(self._addr, self._inbox)
        self._broker.register_local_route(kernel_transport)
        self._cfg.ADDR_KERNEL = self._addr

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
        """
        name=some_name: create or find and return tier with name
        name=NEW_CREATE: create new tier (tier.autocreated=True) and return it
        name=LAST: if last tier exist: find and return last tier, else do like NEW_CREATE
        name=AUTO_CREATING: if last tier.autocreated=False: do like NEW_CREATE, else do like LAST
        name=None: do like AUTO_CREATING
        name != "LAST" and layer_num: create or find tier with layer_num, else layer_num+=1
        """
        if not hasattr(self, '_last_tier_num') or self._last_tier_num is None:
            self._last_tier_num = 0

        # Define all system navigation keywords strictly
        RESERVED = ("LAST", "NEW_CREATE", "AUTO_CREATING")

        # Update counter if explicit layer_num was injected
        if layer_num is not None and name != "LAST":
            self._last_tier_num = max(self._last_tier_num, layer_num)

        # 1. Access by explicit custom string name (skip if it is a command)
        if name and name not in RESERVED:
            if name in self._tiers_by_name:
                tier = self._tiers_by_name[name]
                self._log.inf("Tier '{name}' reused by name.", name=name)
                return tier

        # Internal helpers mapping the docstring state-machine matrix
        def do_last():
            if self._tiers:
                max_num = max(self._tiers.keys())
                return self._tiers[max_num]
            return do_new_create()

        def do_new_create():
            self._last_tier_num += 1
            return build_and_register(self._last_tier_num, f"LAYER_{self._last_tier_num}", True)

        def do_auto_creating():
            if self._tiers:
                max_num = max(self._tiers.keys())
                last_t = self._tiers[max_num]
                if getattr(last_t, 'autocreated', False) is False:
                    return do_new_create()
                return do_last()
            return do_new_create()

        def build_and_register(num: int, t_name: str, auto_flag: bool):
            logger = Logger(f"TIER_{t_name}", self._cfg, self._translator)
            new_tier = Tier(self.tier_view, logger, num, t_name, auto_flag)
            if os.environ.get(f"SANAPO_STUCK_{name}") == "1":
                new_tier.is_flaky = True
                self._log.crt("Tier {nm} born with a BLACK MARK (chronically unstable)!", nm=t_name)
            self._tiers[num] = new_tier
            self._tiers_by_name[t_name] = new_tier
            self._recipes_tiers[num] = {"layer_num": num, "name": t_name, "auto": auto_flag}
            self._log.inf("Tier {name} ({num}) created", name=t_name, num=num)
            return new_tier

        # 2. Evaluate Navigation Commands matrix
        if name == "LAST":
            return do_last()
        if name == "NEW_CREATE":
            return do_new_create()
        if name in (None, "AUTO_CREATING"):
            return do_auto_creating()

        # 3. Handle explicit layer_num assignment fallback
        if layer_num is not None:
            if layer_num in self._tiers:
                return self._tiers[layer_num]
            t_name = name if name else f"LAYER_{layer_num}"
            return build_and_register(layer_num, t_name, False)

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
                    t = "Kernel: created automatically nonexistent Thread {thread_name} for Unit {u_name}"
                    self._log.inf(t, u_name=addr.unit, thread_name=thread_name)
                else:
                    delleting = self._destroy_unit(unit)
                    t = "Unit {u} is created, but Thread {t} is not auto-created. Unit del:{d}"
                    self._log.crt(t, u=addr.unit, t=thread_name, d=delleting)
                    return False
            self._threads[thread_name].add_unit(unit)

            # Tier distribution
            tier = self._tiers.get(tier_layer) or self._tiers_by_name.get(tier_name)
            if tier is None:
                # Direct the exact inputs straight into your smart add_tier factory
                tier = self.add_tier(tier_layer, tier_name)
                if tier:
                    t = "Kernel: created automatically nonexistent Tier {t} for Unit {u}"
                    self._log.inf(t, u=addr.unit, t=f"{tier.name}|{tier.layer_num}")
                else:
                    delleting = self._destroy_unit(unit)
                    t = "Unit {u} is created, but Tier {t} is not auto-created. Unit del:{d}"
                    self._log.crt(t, u=addr.unit, t=f"{tier_name}|{tier_layer}", d=delleting)
                    return False
            
            # For routing
            tier._units.append(unit)
            transport = QueueAdapterTransport(unit.addr, unit._secr._inbox)
            self._broker.register_local_route(transport)

            self._units[addr] = unit
            self._broker.add_local_manifest(name, unit.manifest)
            self._recipes_units[addr] = filtered_params
            return unit

    def add_units(self, configs: list[dict[str, any]]) -> dict[str, BaseUnit]:
        res = {}
        need_dump = False

        for cfg in configs:
            unit = self.add_unit(**cfg)
            if not unit: continue

        if unit.manifest and unit.manifest.is_persistent:
            need_dump = True
        
        if need_dump:
            self._sys_consist_changed()
        return res

    def _build_unit(self, cfg: dict, rebuilding: bool = False) -> BaseUnit | None:
        """Unit factory: from recipe to living object"""
        name = cfg["name"]
        # Addr.
        create = not rebuilding
        addr = self._broker.get_addr(name, create=create, find=True)
        if not addr:
            self._log.err("Unit not assembled. Didn't get Addr. (Name={n})", n=name)
            return None
        # Logger.
        try:
            logger = Logger(addr, self._cfg, self._translator)
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
                broker=self._broker,
                module_class=cfg["m_class"],
                module_params=cfg.get("m_params", {}),
                logger=logger,
                secr=secr,
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

        tags = set()
        if "tags" in module_mnfst:
            tags.update(module_mnfst["tags"])
        if "tags" in param_mnfst:
            tags.update(param_mnfst["tags"])

        try:
            unit.manifest = Manifest(
                addr=addr,
                version=m_data["version"],
                role=m_data["role"],
                is_public=m_data["is_public"],
                is_persistent=m_data["is_persistent"],
                tags=tags
            )
        except (TypeError, ValueError, AttributeError) as e:
            self._log.err(
                "Unit not assembled. Didn't get Manifest (Name={n}): {e}",
                n=name, e=e
            )
            t = "Details: param_m={p}, module_m={m}, final_m={f}"
            self._log.dbg(t, p=param_mnfst, m=module_mnfst, f=m_data)
            return None

        secr._set_unit(unit)
        return unit

    def _destroy_unit(self, unit: BaseUnit) -> None:
        name = unit.addr.unit
        addr = unit.addr
        destroyed = unit.destroy()
        if not destroyed:
            self._log.wrn("Destroy Unit {n} without waiting", n=name)
        self._broker.deregister_addr(addr)

    # TODO in v2: remove tier and thread sync logic for unit collections
    def rebuild_unit(self, unit: BaseUnit, addr: Addr):
        """Destroys and recreates a unit from its recipe"""
        self._log.inf("rebuild Unit {addr}", addr=addr.unit)
        recipe = self._recipes_units.get(addr)
        if not recipe:
            self._log.wrn("no recipe for Unit {name}, rebuild_unit:failed", name=addr.unit)
            return
        manager = self.get_manager_by_addr(addr)
        if manager:
            manager.destroy_unit(unit)
        new_unit = self._build_unit(recipe, True)
        new_unit.addr = addr
        self._units[addr] = new_unit
        if manager:
            manager._units[addr] = new_unit
            manager._init_units[addr] = new_unit
        tier_name = recipe.get("tier_name")
        if tier_name:
            tier_name = tier_name
            tier = self._tiers_by_name[tier_name]
            tier._units = [new_unit if u == unit else u for u in tier._units]
            
        self._log.inf("Unit {name} was rebuiled", name=addr.unit)
    
    # --- Delletions ---

    def del_unit(self, addr: Addr | str) -> bool:
        """
        Gracefully stops and removes a unit from all registries.
        Returns True if the removal process was initiated, False if not found.
        """
        if isinstance(addr, str):
            target_addr = self._broker.get_addr(addr, create=False, find=True)
        elif isinstance(addr, Addr):
            target_addr = addr
        else:
            self._log.err("del_unit: got wrong addr: {addr}", addr=addr)
            return
        unit = self._units.get(target_addr)
        
        if not unit:
            self._log.wrn("Removal failed: Unit {a} not found.", a=addr)
            return False

        # Signal the unit to stop (V1: no deadline waiting here)
        unit.stop()

        # Remove from Thread Manager
        manager = self.get_manager_by_addr(addr)
        if manager:
            manager.remove_unit(str(target_addr.unit))

        # Remove from its Tier
        for tier in self._tiers.values():
            if unit in tier._units:
                tier._units.remove(unit)

        # Final cleanup in Kernel and Broker
        self._destroy_unit(unit) # Calls unit.destroy() and broker.deregister_addr
        self._units.pop(target_addr, None)
        self._recipes_units.pop(target_addr, None)

        self._log.inf("Unit {n} removed from system.", n=target_addr.unit)
        self._broker.remove_local_manifest(target_addr.unit)
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
        self._log.inf("start rebooting")
        self._is_rebooting = True
        self.stop()

    # TODO in v2: calc timeout by Units, Tiers, Threads or/and update with stop-escalation
    def stop(self) -> None:
        """Initiates a graceful, multi-stage architecture shutdown sequence loop."""
        if self._is_shutdowning: 
            return
        self._log.inf("stop")
        self._is_shutdowning = True
        
        # STAGE 1: Mute UDP discovery to prevent new incoming connections and noise
        if getattr(self, '_udp_beacon', None):
            self._udp_beacon.stop()
        if getattr(self, '_udp_listener', None):
            self._udp_listener._is_running = False
            if hasattr(self._udp_listener, 'sock') and self._udp_listener.sock:
                try: self._udp_listener.sock.close()
                except: pass
        self._log.dbg("UDP discovery and beaconing safely terminated")

        # STAGE 2: Cascade shutdown modules via active BootMaster monitoring loop
        self._boot_master.shutdown()
        shutdown_start = perf_counter()
        while self._boot_master.mode == BootTask.SHUTDOWN:
            if perf_counter() - shutdown_start > self._cfg.FW_SUTDOWN_TIMEOUT:
                self._log.err("shutdown: timeout, forcing exit")
                break
            self._boot_master.step()
            for tier in self._tiers.values():
                tier.step()
            sleep(0.005)
        
        # STAGE 3: Final cleanup of the active TCP federation infrastructure
        self._stop_network()
        self.on_stopped()

    def start(self) -> None:
        """Starts all managers and initiates tier ignition"""
        self._log.inf("start")
        self._is_running = True
        self._start_network()
        self._boot_master.boot()

    def step(self) -> None:
        """Execute one cycle of the conductor"""
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

    def loop(self) -> None:
        """Main conductor loop"""
        while self._is_running:
            self.step()

    def _start_network(self) -> None:
        """Starts the network subsystem components with discovery validation."""
        self._tcp_service = TcpService(config=self._cfg, broker=self._broker, logger=self._log)
        self._tcp_service._kernel = self
        self._broker.set_tcp_service(self._tcp_service)
        self._tcp_service.start()

        # Check if the discrete environment requires background discovery beacon loops
        if getattr(self._cfg, 'NEEDS_NET_AUTO_CONNECT', True):
            self._udp_beacon = UdpBeacon(config=self._cfg, logger=self._log)
            self._udp_listener = UdpListener(config=self._cfg, logger=self._log, 
                                             tcp_service=self._tcp_service)
            self._tcp_service._udp_beacon = self._udp_beacon
            
            self._udp_beacon.start()
            self._udp_listener.start()
        else:
            self._log.inf("Network: Automatic discovery beacon loops disabled by configuration.")

    def _stop_network(self) -> None:
        """Gracefully disconnects links and forces thread joins to clear RAM footprints."""
        # 1. Trigger asynchronous stop flags across the network layer layouts
        if getattr(self, '_udp_beacon', None):
            self._udp_beacon._is_running = False
        if getattr(self, '_udp_listener', None):
            self._udp_listener._is_running = False
        if getattr(self, '_tcp_service', None):
            self._tcp_service._is_running = False
            self._tcp_service.disconnect_all()

        # 2. Sequential Thread Join Block: Give OS enough time to flush threads from memory
        # We access python threading references safely via the object handles
        if getattr(self, '_tcp_service', None) and self._tcp_service.is_alive():
            self._tcp_service.join(timeout=0.2)
            
        if getattr(self, '_udp_beacon', None) and self._udp_beacon.is_alive():
            self._udp_beacon.join(timeout=0.2)
            
        if getattr(self, '_udp_listener', None) and self._udp_listener.is_alive():
            self._udp_listener.join(timeout=0.2)
            
        self._log.dbg("All core network service thread contexts joined successfully.")


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

    # Callback for Tier TODO
    def emit_boot_progress(self, text: str, ready: int, total: int):
        """Bridge method: Kernel -> BootMaster."""
        self._boot_master.update_sub_progress_ui(text, ready, total)
    
    # Callback for Tier (and method for self)
    def get_manager_by_addr(self, addr: Addr) -> ThreadManager:
        th_name = self._recipes_units[addr].get("thread_name", "DEFAULT")
        return self._threads[th_name]
    

    # Callback for Secretary
    def resurrect_frame(self, data: dict) -> Frame:
        """
        Converts raw dictionary to a live Frame object.
        For converting dict->Frame in thread of BaseUnit in Secretary.
        """
        return Frame.from_dict(data, self._reg, self._broker)
    
    def on_net_connected(self, frame: Frame) -> None:
        remote_system = frame.payload.get("sys_name")
        self._log.inf("Kernel: Federation link confirmed with node '{s}'. Preparation complete.", s=remote_system)
        self._broker.broadcast_sys_message(SysType.NET_CONNECTED, {"sys_name": remote_system})

    def on_net_disconnected(self, frame: Frame) -> None:
        remote_system = frame.payload.get("sys_name")
        self._log.wrn("Kernel: Federation link with node '{s}' lost. Cleaning up topology.", 
                      s=remote_system)
        
        # 1. Remove the federation route so the broker stops sending messages to a dead link
        if remote_system in self._broker._federation_routes:
            self._broker._federation_routes.pop(remote_system, None)
            
        # 2. Purge all unit addresses and cached manifests belonging to this system
        prefix = f"{remote_system}:"
        with self._broker._addr_lock:
            # Clear remote routing destinations from address book
            keys_addr = [k for k in self._broker._addr_book.keys() if k.startswith(prefix)]
            for k in keys_addr:
                self._broker._addr_book.pop(k, None)
                
            # Clear passport details from service discovery registry to avoid ghosts
            keys_manifest = [k for k in self._broker._remote_manifests.keys() if k.startswith(prefix)]
            for k in keys_manifest:
                self._broker._remote_manifests.pop(k, None)
                
        # 3. Notify all local application modules about the disconnect
        self._broker.broadcast_sys_message(SysType.NET_DISCONNECTED, {"sys_name": remote_system})


    def on_net_manifest_received(self, frame: Frame) -> None:
        remote_system = frame.payload.get("sys_name")
        remote_manifests = frame.payload.get("manifests", {})
        t = "Kernel: received {count} manifests from {sys}"
        self._log.inf(t, count=len(remote_manifests), sys=remote_system)
        
        # Save raw manifest dictionaries directly into the broker's cache
        for addr_str, m_dict in remote_manifests.items():
            self._broker.get_addr(addr_str, create=True, find=False)
            self._broker._remote_manifests[addr_str] = m_dict
        t = "Kernel: Registered and cached {count} passports from '{sys}'"
        self._log.inf(t, count=len(remote_manifests), sys=remote_system)

    # Callback for WatchDog: Exposes live active thread pools dict cleanly
    def get_managers(self) -> dict[str, ThreadManager]:
        return self._threads

    # Callback for WatchDog
    def on_thread_stuck(self, manager: ThreadManager, delay: float):
        """Forcefully terminates and completely recreates a locked OS background thread."""
        t = "Thread '{name}' STUCK for {delay:.2f}s! Executing NUCLEAR RESET."
        self._log.crt(t, name=manager.name, delay=delay)
        success = manager.reload(
            source=UnitSource.CURRENT,
            select=UnitSelection.ALIVE,
            action=ExecutionStrategy.WORKING
        )
        if success:
            self._log.inf("Stalled Thread '{name}' successfully resurrected.", p=manager.name)
        else:
            self._log.err("Thread '{name}' reset failed.", name=manager.name)

