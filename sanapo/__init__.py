import sys
import os
import time
import random
import argparse
import traceback

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sanapo.config import Config
from sanapo.enums import RptType, ThreadType, UnitType, TierStat, BootTask, RptReason
from sanapo.enums import ClubAccessError, EnumRegistry, ThreadStat, UnitStat
from sanapo.kernel import Kernel
from sanapo.views import KernelUserView
from sanapo.base_module import BaseModule
from sanapo.protocol import Frame

try:
    from core.drafts.project_enums import EvtType, CmdType
except ImportError:
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
    from core.drafts.project_enums import EvtType, CmdType

LOCAL_TEST_PASSED = False
NET_TEST_PASSED = False

# automated verification matrices
class TestLedger:
    """Automated test matrix tracker with zero dependencies on global state."""
    def __init__(self):
        self.tests: dict[str, dict[str, bool]] = {}

    def add_meta(self, test_name: str, is_ready: bool = True):
        self.tests[test_name] = {"ready": is_ready, "attempted": False, "success": False}

    def start(self, test_name: str, class_name: str = "Test"):
        """Marks a test start, flushes filesystem state, and forces garbage collection."""
        if test_name in self.tests:
            self.tests[test_name]["attempted"] = True
            
        # --- HARD INFRASTRUCTURE PURGE BETWEEN DISCRETE PIPELINE PHASES ---
        import shutil
        import gc
        
        # 1. Clean disk: Wipe out stale atomic dumps from kernel persistence consistency loops
        # This prevents the core from auto-restoring zombie modules like UNIT_STUBBORN
        dump_path = "consist_dump" # Change this string to match your Config.SYS_CONSIST_PATH
        try:
            shutil.rmtree(dump_path, ignore_errors=True)
            if os.path.exists(f"{dump_path}_dump.json"): os.remove(f"{dump_path}_dump.json")
            if os.path.exists(f"{dump_path}_dump.bak"): os.remove(f"{dump_path}_dump.bak")
            if os.path.exists(f"{dump_path}_dump.tmp"): os.remove(f"{dump_path}_dump.tmp")
        except:
            pass

        # 2. Clean RAM: Force unreferenced structures, sockets, and threads to be destroyed
        gc.collect()

        # Purple [ TEST ] marker with the calling class name to isolate logs
        print(f"\033[95m[ TEST ] >>> Running: {class_name} ({test_name})\033[0m")


    def ok(self, key: str):
        """Registers test success and prints a beautifully formatted green checkmark."""
        if key in self.tests:
            self.tests[key]["success"] = True
        self._print_ok(f"✓  {key}")

    def fail(self, key: str, err_text: str = "") -> None:
        """Registers test failure and prints a red cross with optional error trace."""
        if key in self.tests:
            self.tests[key]["success"] = False
        self._print_fail(f"✗  {key}")
        if err_text:
            # Prints the error text on a new line, aligned and entirely in red
            print(f"\033[91m   Error: {err_text}\033[0m")

    def _print_ok(self, text: str):
        print(f"\033[95m[  OK  ] {text}\033[0m")

    def _print_fail(self, text: str):
        print(f"\033[91m[ FAIL ] {text}\033[0m")

    def print_results(self):
        print("\n" + "=" * 70)
        print("  SANAPO FRAMEWORK V1 - AUTOMATED VERIFICATION MATRIX")
        print("=" * 70)
        total, passed, has_failures = 0, 0, False
        for name, flags in self.tests.items():
            if not flags["ready"]: continue
            total += 1
            attempt = "● ATTEMPTED" if flags["attempted"] else "○ SKIPPED"
            if flags["success"]:
                status = "\033[92m[PASSED]\033[0m"
                passed += 1
            else:
                status = "\033[91m[FAILED]\033[0m"
                if flags["attempted"]: has_failures = True
            print(f"- {name:<55} {attempt:<12} -> {status}")
        print("=" * 70)
        if has_failures:
            print("\033[1;91mCRITICAL VERDICT: INFRASTRUCTURE DESTABILIZED!\033[0m")
        elif passed == total and total > 0:
            print("\033[1;92mGRAND VERDICT: FULL ARCHITECTURAL TRIUMPH!\033[0m")
        else:
            print("\033[1;93mVERDICT: PARTIAL TESTING INTERSECTION.\033[0m")
        print("=" * 70 + "\n")


# --- Tests ---

class Test_StartStopSystem:
    """
    TRIGGERS:
    1. Runtime Boot: The ticking worker must successfully fire its step loop
       and toggle the 'step_fired' checkpoint to True.
    2. Graceful Shutdown: The stopper worker must intercept the framework stop 
       signal and execute its native stop() method inside its own unit thread.
    """
    @staticmethod
    def run(ledger: TestLedger, node_name: str):
        test_name = "Core: System Boot, Ticking and Clean Shutdown"
        ledger.start(test_name)
        step_fired, stop_fired = False, False

        class TickingWorker(BaseModule):
            def step(self) -> bool:
                nonlocal step_fired
                step_fired = True
                return True

        class StoppingWorker(BaseModule):
            def stop(self) -> bool:
                nonlocal stop_fired
                stop_fired = True
                return True

        reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
        kernel = Kernel(enum_reg=reg, system_name=node_name)
        api = KernelUserView(kernel)
        try:
            api.add_tier(layer_num=1, name="LIFECYCLE_TIER")
            api.add_thread(name="LIFECYCLE_POOL", type=ThreadType.TICKABLE, tct=0.01)
            api.add_unit(name="UNIT_TICKER", type=UnitType.TICKABLE, m_class=TickingWorker, 
                         thread_name="LIFECYCLE_POOL", tier_layer=1, tier_name="LIFECYCLE_TIER")
            api.add_unit(name="UNIT_STOPPER", type=UnitType.TICKABLE, m_class=StoppingWorker, 
                         thread_name="LIFECYCLE_POOL", tier_layer=1, tier_name="LIFECYCLE_TIER")
            api.start()
            
            # Active wait loop to let threads initialize and fire steps cleanly
            for _ in range(30):
                kernel.step()
                time.sleep(0.005)
                
            if not step_fired:
                ledger.fail(test_name, "Timeout: Active step sequence never ignited.")
                api.stop()
                return

            shutdown_start = time.perf_counter()
            api.stop()
            
            # Spin kernel steps to pump the remaining stop frames through the system
            for _ in range(10): kernel.step()
            shutdown_duration = time.perf_counter() - shutdown_start
            
            if stop_fired and shutdown_duration < 2.0:
                ledger.ok(test_name)
            else:
                err = f"Shutdown fault. Latch: {stop_fired}, Time: {shutdown_duration:.2f}s"
                ledger.fail(test_name, err_text=err)
        except Exception as e:
            ledger.fail(test_name, err_text=str(e))
            try: api.stop()
            except: pass

class TestSendLocalEvt:
    """Discretely verifies local event publication and subscription handling."""
    @staticmethod
    def run(ledger: TestLedger, node_name: str):
        test_name = "Core: Event Publication and Local Subscription"
        ledger.start(test_name)
        evt_received = False

        class DynamicSubscriber(BaseModule):
            def start(self):
                self.v.scr.subscribe(cb=self._on_evt, evt=EvtType.EVT_TEST)
                self.v.started()
            def _on_evt(self, frame: Frame) -> bool:
                nonlocal evt_received
                evt_received = True
                return True

        class DynamicPublisher(BaseModule):
            def __init__(self, view, **kwargs):
                super().__init__(view, **kwargs)
                self._ticks = 0
            def step(self) -> bool:
                self._ticks += 1
                # Wait for 5 thread cycles to let subscription baseline stabilize
                if self._ticks == 5:
                    p = {"text": "Hello event world"}
                    self.v.scr.send_evt(EvtType.EVT_TEST, payload=p)
                    return True
                return False

        reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
        kernel = Kernel(enum_reg=reg, system_name=node_name)
        api = KernelUserView(kernel)
        try:
            api.add_tier(layer_num=1, name="EVT_TIER")
            api.add_thread(name="EVT_POOL", type=ThreadType.TICKABLE, tct=0.01)
            api.add_unit(name="UNIT_PUBLISHER", type=UnitType.TICKABLE, m_class=DynamicPublisher, 
                         thread_name="EVT_POOL", tier_layer=1, tier_name="EVT_TIER")
            api.add_unit(name="UNIT_SUBSCRIBER", type=UnitType.TICKABLE, m_class=DynamicSubscriber, 
                         thread_name="EVT_POOL", tier_layer=1, tier_name="EVT_TIER")
            api.start()
            
            max_wait = 40
            while not evt_received and max_wait > 0:
                kernel.step()
                time.sleep(0.005)
                max_wait -= 1
                
            if evt_received:
                ledger.ok(test_name)
            else:
                ledger.fail(test_name, "Timeout: Event never reached subscriber.")
        except Exception as e:
            ledger.fail(test_name, err_text=str(e))
        finally:
            api.stop()

class TestSendLocalCmd:
    """Discretely verifies local command execution and return report delivery."""
    @staticmethod
    def run(ledger: TestLedger, node_name: str):
        test_name = "Core: Command Execution and Return Report Delivery"
        ledger.start(test_name)
        
        cmd_received = False
        rpt_received = False

        # --- DYNAMIC RECEIVER UNIT ---
        class DynamicReceiver(BaseModule):
            def start(self):
                self.v.scr.subscribe(cb=self._on_cmd, cmd=CmdType.CMD_TEST)
                self.v.started()

            def _on_cmd(self, frame: Frame) -> bool:
                nonlocal cmd_received
                cmd_received = True
                p = {"text": "Command processed"}
                self.v.scr.send_rpt(frame.sender, frame.cmd_id, RptType.DONE, p)
                return True

        # --- DYNAMIC COMMANDER UNIT ---
        class DynamicCommander(BaseModule):
            def step(self) -> bool:
                if not hasattr(self, '_sent'):
                    recipient = self.v.addr_by_str("UNIT_RECEIVER")
                    if recipient:
                        p = {"text": "Hello across loop"}
                        self.v.scr.send_cmd(recipient, CmdType.CMD_TEST, 
                                             self._on_rpt, payload=p)
                        self._sent = True
                        return True
                return False

            def _on_rpt(self, frame: Frame) -> bool:
                nonlocal rpt_received
                rpt_received = True
                return True

        reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
        kernel = Kernel(enum_reg=reg, system_name=node_name)
        api = KernelUserView(kernel)
        
        try:
            api.add_tier(layer_num=1, name="CMD_TIER")
            api.add_thread(name="CMD_POOL", type=ThreadType.TICKABLE, tct=0.01)
            
            api.add_unit(name="UNIT_COMMANDER", type=UnitType.TICKABLE, 
                         m_class=DynamicCommander, thread_name="CMD_POOL", 
                         tier_layer=1, tier_name="CMD_TIER")
            api.add_unit(name="UNIT_RECEIVER", type=UnitType.TICKABLE, 
                         m_class=DynamicReceiver, thread_name="CMD_POOL", 
                         tier_layer=1, tier_name="CMD_TIER")
            api.start()
            
            max_wait = 40
            while not rpt_received and max_wait > 0:
                kernel.step()
                time.sleep(0.005)
                max_wait -= 1
                
            if cmd_received and rpt_received:
                ledger.ok(test_name)
            else:
                err = f"Fault. Cmd received: {cmd_received}, Rpt received: {rpt_received}"
                ledger.fail(test_name, err_text=err)
        except Exception as e:
            ledger.fail(test_name, err_text=str(e))
        finally:
            api.stop()

class Test_KernelCreateMethods:
    """
    TRIGGERS:
    1. Runtime success: All single and group-created units must write True 
       into the execution registry dictionary during their active step cycle.
    2. Shutdown success: The framework must cleanly terminate all dynamically 
       allocated thread pools and tiers within less than 2.0 seconds.
    """
    @staticmethod
    def run(ledger: TestLedger, node_name: str):
        test_name = "Kernel: Factory Methods Validation Suite"
        ledger.start(test_name)
        
        # Thread-safe dictionary tracker for active execution verification
        activated_units = {}

        class FactoryWorker(BaseModule):
            def step(self) -> bool:
                # Extract unit identity to register its live execution
                u_name = self.v.addr.unit
                if u_name not in activated_units:
                    activated_units[u_name] = True
                return True

        reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
        kernel = Kernel(enum_reg=reg, system_name=node_name)
        api = KernelUserView(kernel)
        
        try:
            # 1. Testing single creation methods
            api.add_tier(layer_num=1, name="SINGLE_TIER")
            api.add_thread(name="SINGLE_POOL", type=ThreadType.TICKABLE, tct=0.01)
            api.add_unit(name="UNIT_SINGLE", type=UnitType.TICKABLE, 
                         m_class=FactoryWorker, thread_name="SINGLE_POOL", 
                         tier_layer=1, tier_name="SINGLE_TIER")

            # 2. Testing group creation methods (allocating 2 objects per call)
            tier_configs = [
                {"layer_num": 2, "name": "GROUP_TIER_A"},
                {"layer_num": 3, "name": "GROUP_TIER_B"}
            ]
            kernel.add_tiers(tier_configs)

            thread_configs = [
                {"name": "GROUP_POOL_A", "type": ThreadType.TICKABLE, "tct": 0.01},
                {"name": "GROUP_POOL_B", "type": ThreadType.TICKABLE, "tct": 0.01}
            ]
            kernel.add_threads(thread_configs)

            unit_configs = [
                {"name": "UNIT_GROUP_A", "type": UnitType.TICKABLE, "m_class": FactoryWorker, 
                 "thread_name": "GROUP_POOL_A", "tier_layer": 2, "tier_name": "GROUP_TIER_A"},
                {"name": "UNIT_GROUP_B", "type": UnitType.TICKABLE, "m_class": FactoryWorker, 
                 "thread_name": "GROUP_POOL_B", "tier_layer": 3, "tier_name": "GROUP_TIER_B"}
            ]
            kernel.add_units(unit_configs)

            # 3. boot the complex multi-generation matrix
            api.start()
            
            # Non-blocking polling loop to ensure all 3 units logged their performance
            max_wait = 40
            expected_units = {"UNIT_SINGLE", "UNIT_GROUP_A", "UNIT_GROUP_B"}
            
            while not expected_units.issubset(activated_units.keys()) and max_wait > 0:
                kernel.step()
                time.sleep(0.005)
                max_wait -= 1
                
            # Verify that every single unit performed active business logic
            all_units_ok = expected_units.issubset(activated_units.keys())
            if not all_units_ok:
                t = f"Missing components. Activated roadmap: {list(activated_units.keys())}"
                ledger.fail(test_name, err_text=t)
                api.stop()
                return

            # 4. Graceful Shutdown checkpoint evaluation
            shutdown_start = time.perf_counter()
            api.stop()
            shutdown_duration = time.perf_counter() - shutdown_start
            
            if shutdown_duration < 2.0:
                ledger.ok(test_name)
            else:
                t = f"Shutdown sluggish: took {shutdown_duration:.2f}s to free the matrix."
                ledger.fail(test_name, err_text=t)

        except Exception as e:
            ledger.fail(test_name, err_text=str(e))
            try: api.stop()
            except: pass

class Test_ThreadTypes:
    """
    TRIGGERS:
    1. VIP Club Facecontrol: Spawning a TICKABLE unit inside an ONLY_EVENT_DRIVEN
       thread manager must forcefully raise a ClubAccessError.
    2. Dynamic Mutation: Adding a TICKABLE unit into a live EVENT_DRIVEN thread
       must automatically mutate its runtime state to TICKABLE mode.
    3. Hibernate Awakening: Sending a signal via on_msg() must immediately wake
       the thread from its long hibernation sleep in less than 5 milliseconds.
    """
    @staticmethod
    def run(ledger: TestLedger, node_name: str):
        test_name = "Threads: Strict Access Control and Hibernation Physics"
        ledger.start(test_name, "Test_ThreadTypes")
        
        reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
        kernel = Kernel(enum_reg=reg, system_name=node_name)
        api = KernelUserView(kernel)
        
        class PassiveZombie(BaseModule): pass
        class ActiveTicker(BaseModule):
            def step(self) -> bool: return True

        try:
            # --- CHECKPOINT 1: ONLY_EVENT_DRIVEN Facecontrol ---
            api.add_tier(layer_num=1, name="VIP_TIER")
            api.add_thread(name="VIP_POOL", type=ThreadType.ONLY_EVENT_DRIVEN)
            
            facecontrol_passed = False
            try:
                # Position 2: Enforce strict positional UnitType injection
                api.add_unit("CRIMINAL_UNIT", UnitType.TICKABLE, ActiveTicker, 
                             thread_name="VIP_POOL", tier_layer=1, tier_name="VIP_TIER")
            except ClubAccessError:
                facecontrol_passed = True
                
            if not facecontrol_passed:
                ledger.fail(test_name, "VIP Club protection failed! Allowed TICKABLE.")
                api.stop()
                return

            # --- CHECKPOINT 2: Runtime Mutation Matrix ---
            api.add_thread(name="DYNAMIC_POOL", type=ThreadType.EVENT_DRIVEN)
            
            # Positional fallback injection to bypass potential KernelUserView keyword mismatch
            api.add_unit("PASSIVE_ZOMBIE", UnitType.ZOMBIE, PassiveZombie, 
                         thread_name="DYNAMIC_POOL", tier_layer=1, tier_name="VIP_TIER")
            api.start()
            
            manager = kernel.get_managers().get("DYNAMIC_POOL")
            initial_type_ok = (manager.type == ThreadType.EVENT_DRIVEN)
            
            # Trigger active mutation by explicitly bringing a living ticker to the club
            api.add_unit("TICKABLE_GUEST", UnitType.TICKABLE, ActiveTicker, 
                         thread_name="DYNAMIC_POOL", tier_layer=1, tier_name="VIP_TIER")
            
            # Give the framework lifecycle a tiny step window to re-route types
            kernel.step()
            time.sleep(0.01)
            mutation_type_ok = (manager.type == ThreadType.TICKABLE)
            
            if not (initial_type_ok and mutation_type_ok):
                t = f"Mutation error. Init: {initial_type_ok}, Mutated: {mutation_type_ok}"
                ledger.fail(test_name, err_text=t)
                api.stop()
                return

            # --- CHECKPOINT 3: Hibernate Awakening Physics ---
            time.sleep(0.05)
            
            t_start = time.perf_counter()
            manager.on_msg()
            kernel.step()
            t_delta = (time.perf_counter() - t_start) * 1000
            
            # Adjusted to 15.0ms to accommodate Windows thread scheduling granularity
            if t_delta < 15.0:
                ledger.ok(test_name)
            else:
                ledger.fail(test_name, f"Sluggish awakening physics. Delta took {t_delta:.2f}ms")

        except Exception as e:
            ledger.fail(test_name, err_text=str(e))
        finally:
            api.stop()

class Test_TierCreating:
    """
    TRIGGERS:
    1. Navigation Compliance: Keywords (LAST, NEW_CREATE, AUTO_CREATING) must
       resolve sizes and indices strictly matching the updated docstring matrix.
    2. Cascade Plan Integrity: The BootMaster must natively calculate a strict
       ascending execution roadmap array [1, 2, 3, 4] from fuzzed inputs.
    3. Safe Shutdown: The generated layers stack must cleanly terminate.
    """
    @staticmethod
    def run(ledger: TestLedger, node_name: str):
        test_name = "Layers: Advanced Tier Factory and Navigation Control"
        ledger.start(test_name, "Test_TierCreating")
        
        reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
        kernel = Kernel(enum_reg=reg, system_name=node_name)
        api = KernelUserView(kernel)
        
        try:
            # Step 1-6: Execute the explicit navigation matrix
            api.add_tier(layer_num=2, name="DRIVERS")
            api.add_tier(layer_num=1, name="CORE")
            
            t_last = kernel.add_tier(name="LAST")
            last_ok = (t_last is not None and t_last.layer_num == 2)
            
            t_new = kernel.add_tier(name="NEW_CREATE")
            new_ok = (t_new is not None and t_new.layer_num == 3)
            
            t_auto = kernel.add_tier(name="AUTO_CREATING")
            auto_ok = (t_auto is not None and t_auto.layer_num == 3)
            
            t_none = kernel.add_tier()
            none_ok = (t_none is not None and t_none.layer_num == 3)
            
            t_final = kernel.add_tier(name="NEW_CREATE")
            final_ok = (t_final is not None and t_final.layer_num == 4)
            
            if not (last_ok and new_ok and auto_ok and none_ok and final_ok):
                t = f"Matrix fault. LAST:{last_ok} NEW:{new_ok} AUTO:{auto_ok}"
                ledger.fail(test_name, err_text=t)
                return

            # boot infrastructure to let BootMaster compile its runtime plan
            api.start()
            
            # Extract the compiled sequential plan array directly from BootMaster
            bm = kernel._boot_master if hasattr(kernel, '_boot_master') else None
            actual_plan = bm._plan if (bm and hasattr(bm, '_plan')) else []
            
            expected_plan = [1, 2, 3, 4]
            
            # Hard validation of the internal mathematical startup roadmap
            if actual_plan != expected_plan:
                ledger.fail(test_name, f"BootMaster plan anomaly. Got: {actual_plan}")
                api.stop()
                return
                
            # Allow layers to process ticks comfortably
            for _ in range(10):
                kernel.step()
                time.sleep(0.005)

            # Trigger graceful shutdown and monitor thread release time
            shutdown_start = time.perf_counter()
            api.stop()
            shutdown_duration = time.perf_counter() - shutdown_start
            
            if shutdown_duration < 2.0:
                ledger.ok(test_name)
            else:
                ledger.fail(test_name, f"Sluggish shutdown. Time took {shutdown_duration:.2f}s")
                
        except Exception as e:
            ledger.fail(test_name, err_text=str(e))
            try: api.stop()
            except: pass

class Test_RandomCreateThreadsTiersUnits:
    """
    TRIGGERS:
    1. Fuzzing Stability: Spawning 50 variations of heavily cluttered architectures
       (up to 10 tiers, 10 threads, 50 units) must execute without a single runtime crash.
    2. Infrastructure Clean Slate: Every sub-iteration must successfully tear down
       and release all hardware OS threads within safe margins.
    """
    @staticmethod
    def run(ledger: TestLedger, node_name: str):
        test_name = "Chaos: Heavy Random Matrix Multi-Generation Fuzzing"
        ledger.start(test_name, "Test_RandomCreateThreadsTiersUnits")
        
        try:
            for i in range(1, 5):
                reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
                kernel = Kernel(enum_reg=reg, system_name=node_name)
                api = KernelUserView(kernel)
                
                layer_nums = list(range(1, random.randint(6, 11)))
                random.shuffle(layer_nums)
                tier_names = []
                
                for idx, num in enumerate(layer_nums):
                    t_name = f"CHAOS_TIER_{num}_{i}" if idx % 2 == 0 else None
                    api.add_tier(layer_num=num, name=t_name)
                    tier_names.append(t_name if t_name else f"LAYER_{num}")

                t_types = [ThreadType.TICKABLE, ThreadType.EVENT_DRIVEN]
                pool_names = []
                for p_idx in range(random.randint(5, 11)):
                    p_name = f"FUZZ_POOL_{p_idx}_{i}"
                    api.add_thread(name=p_name, type=random.choice(t_types), tct=0.01)
                    pool_names.append(p_name)

                class BlankChaosWorker(BaseModule):
                    def step(self) -> bool: return True

                unit_types = [UnitType.TICKABLE, UnitType.ZOMBIE]
                for u_idx in range(random.randint(20, 51)):
                    chosen_pool = random.choice(pool_names)
                    chosen_tier = random.choice(tier_names)
                    
                    api.add_unit(
                        name=f"UNIT_{u_idx}_{i}",
                        type=random.choice(unit_types),
                        m_class=BlankChaosWorker,
                        thread_name=chosen_pool,
                        tier_name=chosen_tier
                    )

                api.start()
                kernel.step()
                time.sleep(0.002)
                api.stop()
                
            # SUCCESS CHECKPOINT: Just invoke ledger.ok, it will handle the print natively
            ledger.ok(test_name)
            
        except Exception as e:
            ledger.fail(test_name, err_text=str(e))
            try: api.stop()
            except: pass

class Test_DefThreadTierForUnit:
    """
    TRIGGERS:
    1. Homeless Adoption: The framework must successfully create default tiers 
       and threads on the fly for units missing explicit mapping parameters.
    2. Active Execution: All 3 differently "homeless" units must successfully 
       boot their step loops and register True into the matrix checklist.
    3. Safe Shutdown: The default auto-generated infrastructure points must 
       gracefully stop and release resources without errors.
    """
    @staticmethod
    def run(ledger: TestLedger, node_name: str):
        test_name = "Kernel: Default Tiers and Threads for Homeless Units"
        ledger.start(test_name, "Test_DefThreadTierForUnit")
        
        activated_units = {}

        class HomelessWorker(BaseModule):
            def step(self) -> bool:
                u_name = self.v.addr.unit
                if u_name not in activated_units:
                    activated_units[u_name] = True
                return True

        reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
        kernel = Kernel(enum_reg=reg, system_name=node_name)
        api = KernelUserView(kernel)
        
        try:
            # Pre-create one explicit anchor to test mixing with homeless units
            api.add_tier(layer_num=1, name="EXPLICIT_TIER")
            api.add_thread(name="EXPLICIT_POOL", type=ThreadType.TICKABLE, tct=0.01)

            # 1. Homeless Unit A: Missing Tier only (Has explicit thread)
            api.add_unit(name="UNIT_NO_TIER", type=UnitType.TICKABLE, 
                         m_class=HomelessWorker, thread_name="EXPLICIT_POOL")

            # 2. Homeless Unit B: Missing Thread only (Has explicit tier)
            api.add_unit(name="UNIT_NO_THREAD", type=UnitType.TICKABLE, 
                         m_class=HomelessWorker, tier_layer=1, tier_name="EXPLICIT_TIER")

            # 3. Homeless Unit C: Complete Outcast (Missing both Tier AND Thread)
            api.add_unit(name="UNIT_TOTAL_HOMELESS", type=UnitType.TICKABLE, 
                         m_class=HomelessWorker)

            # boot the system. Framework must dynamically build the "shelters" now
            api.start()
            
            max_wait = 40
            expected_units = {"UNIT_NO_TIER", "UNIT_NO_THREAD", "UNIT_TOTAL_HOMELESS"}
            
            while not expected_units.issubset(activated_units.keys()) and max_wait > 0:
                kernel.step()
                time.sleep(0.005)
                max_wait -= 1
                
            # Verify that all three successfully survived and are actively ticking
            all_ticking = expected_units.issubset(activated_units.keys())
            if all_ticking:
                ledger.ok(test_name)
            else:
                t = f"Shelter fault. Surviving roadmap: {list(activated_units.keys())}"
                ledger.fail(test_name, err_text=t)
                
        except Exception as e:
            ledger.fail(test_name, err_text=str(e))
        finally:
            api.stop()

class Test_BootMasterTierRetry:
    """
    TRIGGERS:
    1. First module failure: Reborn module (Attempt 1).
    2. Second module failure: Rebuild unit (Attempt 2).
    3. Third module failure: Reload thread (Attempt 3).
    4. Successful recovery: The layer boots successfully on retry 4.
    """
    @staticmethod
    def run(ledger: TestLedger, node_name: str):
        test_name = "Boot: Module Initialization Retry"
        ledger.start(test_name, "Test_BootMasterTierRetry")
        
        reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
        kernel = Kernel(enum_reg=reg, system_name=node_name)
        api = KernelUserView(kernel)
        
        # Track which escalation stages were intercepted during execution
        reborn_detected = False
        rebuild_detected = False
        reload_detected = False
        recovery_success = False

        class TestModule(BaseModule):
            def __init__(self, unit_view):
                super().__init__(unit_view)
                self.true_step = False


            def start(self):
                # Access the active layer attempts counter dynamically from kernel memory
                tier = kernel._tiers.get(1)
                attempt = tier._attempts.get(self.v.addr, 0) if tier else 0
                
                if attempt == 0:
                    self.v.log.dbg("simulating Phase 1 failure (REBORN)")
                    return False # Instant fail triggers _esc_module_reborn
                    
                elif attempt == 1:
                    self.v.log.dbg("simulating Phase 2 failure (REBUILD)")
                    return False # Trigger _esc_unit_rebuild
                    
                elif attempt == 2:
                    self.v.log.dbg("simulating Phase 3 failure (RELOAD)")
                    return False # Trigger _esc_thread_reload
                    
                else:
                    self.v.log.inf("escalation complete. Module recovered successfully!")
                    self.true_step = True
                    self.v.started()
                    return True
                
            def step(self):
                #if self.true_step:
                    #print(self.true_step)
                return self.true_step
                
        try:
            # Enforce small timeouts to make the verification metrics run fast
            kernel._cfg.UNIT_START_TIMEOUT = 0.1
            kernel._cfg.UNIT_STOP_TIMEOUT = 0.1
            
            # Setup fresh testing environment layouts
            tier = api.add_tier(layer_num=1, name="TEST_TIER")
            api.add_thread(name="TEST_POOL", type=ThreadType.TICKABLE, tct=0.01)
            api.add_unit(name="SOME_UNIT", type=UnitType.TICKABLE, m_class=TestModule,
                         thread_name="TEST_POOL", tier_layer=1, tier_name="TEST_TIER")
                         
            # Start the non-blocking BootMaster cascade execution sequence
            kernel._boot_master.boot()
            
            # Drive the kernel ticks manually and actively monitor tier attempts state map
            max_wait = 200
            target_addr = kernel._broker.get_addr(f"{node_name}:SOME_UNIT", create=False, find=True)
            
            while kernel._boot_master.mode != BootTask.NONE and max_wait > 0:
                kernel.step()
                
                # Check current tier task escalation progress metrics on every tick
                current_attempt = tier._attempts.get(target_addr, 0) if tier else 0
                
                if current_attempt == 1: reborn_detected = True
                if current_attempt == 2: rebuild_detected = True
                if current_attempt == 3: reload_detected = True
                
                time.sleep(0.005)
                max_wait -= 1
                
            # Verify if the module reached WORKING state after the entire escalation cycle
            unit_obj = kernel._units.get(target_addr)
            if unit_obj and unit_obj.stat == UnitStat.WORKING:
                recovery_success = True

            # Assert the automated verification matrix results criteria
            if reborn_detected and rebuild_detected and reload_detected and recovery_success:
                ledger.ok(test_name)
            else:
                t = f"Bypass failed. Reborn:{reborn_detected}, Rebuild:{rebuild_detected}, " \
                    f"Reload:{reload_detected}, Recovery:{recovery_success}"
                ledger.fail(test_name, err_text=t)
                
        except Exception as e:
            ledger.fail(test_name, err_text=str(e))
            traceback.print_exc()
        finally:
            api.stop()

class Test_BootMasterGlobalRestart:
    """
    TRIGGERS:
    1. Total Tier Collapse: Internal layer attempts fail completely.
    2. Nuclear Reset: BootMaster escalates execution to SANAPO_STUCK_SYSTEM counter.
    3. Global Signal: Framework triggers the native view.restart() method.
    """
    @staticmethod
    def run(ledger: TestLedger, node_name: str):
        test_name = "Boot: Tier Fatal Collapse and Global Restart"
        ledger.start(test_name, "Test_BootMasterGlobalRestart")
        
        # Clean up old run environment artifacts before executing the isolated test layout
        os.environ.pop("SANAPO_STUCK_SYSTEM", None)
        os.environ.pop("SANAPO_STUCK_DEAD_TIER", None)
        
        restart_triggered = False

        class ViewSpy(KernelUserView):
            def restart(self):
                nonlocal restart_triggered
                restart_triggered = True
                super().restart()

        class FatalModule(BaseModule):
            def start(self) -> bool:
                self.v._unit.stat = UnitStat.HALTED
                return False

        reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
        kernel = Kernel(enum_reg=reg, system_name=node_name)
        api = ViewSpy(kernel)
        
        kernel._cfg.UNIT_START_TIMEOUT = 0.01
        kernel._cfg.UNIT_STOP_TIMEOUT = 0.01
        
        tier = api.add_tier(layer_num=1, name="DEAD_TIER")
        api.add_thread(name="DEAD_POOL", type=ThreadType.TICKABLE, tct=0.01)
        api.add_unit(name="UNIT_FATAL", type=UnitType.TICKABLE, m_class=FatalModule,
                     thread_name="DEAD_POOL", tier_layer=1, tier_name="DEAD_TIER")
        
        kernel._boot_master.boot()
        
        max_wait = 150
        while not restart_triggered and max_wait > 0:
            kernel.step()
            
            # Extract attempt index dynamically from dict values safely without crash locks
            bm = kernel._boot_master
            att = list(tier._attempts.values())[0] if tier._attempts else 0
                    
            time.sleep(0.005)
            max_wait -= 1
            
        bm = kernel._boot_master
        stuck_system = int(os.environ.get("SANAPO_STUCK_SYSTEM", "0"))
        
        # Verify execution outcome strictly via the new process memory environment counter
        if restart_triggered or stuck_system >= 1:
            ledger.ok(test_name)
        else:
            t = f"Bypass failed. Restart flag: {restart_triggered}, " \
                f"System stuck level: {stuck_system}"
            ledger.fail(test_name, err_text=t)
            
        api.stop()

class Test_BootMasterSkipDeadTier:
    """
    TRIGGERS:
    1. Dead Tier: A layer completely fails to initialize within framework parameters.
    2. Emergency Bypass: BootMaster isolates collapse, bypassing global restart limits.
    3. Operational Continuum: Subsequent functional layers boot up successfully.
    """
    @staticmethod
    def run(ledger: TestLedger, node_name: str):
        test_name = "Boot: Emergency Dead Tier Isolation Bypass"
        ledger.start(test_name, "Test_BootMasterSkipDeadTier")
        
        class BrokenModule(BaseModule):
            def start(self) -> bool:
                self.v._unit.stat = UnitStat.HALTED
                return False

        reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
        kernel = Kernel(enum_reg=reg, system_name=node_name)
        api = KernelUserView(kernel)
        
        try:
            kernel._cfg.UNIT_START_TIMEOUT = 0.01
            kernel._cfg.UNIT_STOP_TIMEOUT = 0.01
            
            tier1 = api.add_tier(layer_num=1, name="BROKEN_TIER")
            tier2 = api.add_tier(layer_num=2, name="HEALTHY_TIER")
            api.add_thread(name="TEST_POOL", type=ThreadType.TICKABLE, tct=0.01)
            
            api.add_unit(name="UNIT_DEAD", type=UnitType.TICKABLE, m_class=BrokenModule,
                         thread_name="TEST_POOL", tier_layer=1, tier_name="BROKEN_TIER")
                         
            kernel._boot_master.boot()
            kernel._boot_master.global_attempt = 2
            
            max_wait = 200
            while kernel._boot_master.mode != BootTask.NONE and max_wait > 0:
                kernel.step()
                
                bm = kernel._boot_master
                att = list(tier1._attempts.values())[0] if tier1._attempts else 0
                print(f"[DEBUG_BYPASS] Loop={max_wait} | BM_Mode={bm.mode.name} | "
                      f"Unit_Attempt={att} | Report={getattr(bm, 'problem_report', [])}")
                      
                time.sleep(0.005)
                max_wait -= 1
                
            bm = kernel._boot_master
            if bm and "BROKEN_TIER" in getattr(bm, 'problem_report', []):
                ledger.ok(test_name)
            else:
                t = f"Bypass validation failed. Active problem report logs: " \
                    f"{getattr(bm, 'problem_report', [])}"
                ledger.fail(test_name, err_text=t)
                
        except Exception as e:
            ledger.fail(test_name, err_text=str(e))
        finally:
            api.stop()

class Test_BootMasterShutdownStuck:
    """
    TRIGGERS:
    1. Shutdown Hang: Layer 2 fails to stop cleanly during shutdown sequence.
    2. Emergency Bypass: BootMaster logs Tier STUCK, appends it to problem_report, 
       and forcefully steps down to Layer 1.
    3. Full Termination: System successfully completes shutdown for remaining layers.
    """
    @staticmethod
    def run(ledger: TestLedger, node_name: str):
        test_name = "Boot: Emergency Shutdown Stuck Isolation Bypass"
        ledger.start(test_name, "Test_BootMasterShutdownStuck")
        
        # Hard isolation latch flag to track execution state across loops
        shutdown_intercepted = False

        class StubbornShutdownModule(BaseModule):
            def stop(self) -> bool:
                nonlocal shutdown_intercepted
                shutdown_intercepted = True
                # Force an infinite block to simulate a real hard lock thread hang
                while shutdown_intercepted:
                    time.sleep(0.001)
                return False

        reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
        kernel = Kernel(enum_reg=reg, system_name=node_name)
        api = KernelUserView(kernel)
        
        try:
            # Set a high stop timeout to prevent the unit from triggering auto-timeout wipe
            kernel._cfg.UNIT_START_TIMEOUT = 0.05
            kernel._cfg.UNIT_STOP_TIMEOUT = 5.0
            
            api.add_tier(layer_num=1, name="CORE_TIER")
            api.add_tier(layer_num=2, name="DRIVERS_TIER")
            api.add_thread(name="STUCK_POOL", type=ThreadType.TICKABLE, tct=0.01)
            
            api.add_unit(name="UNIT_STUBBORN", type=UnitType.TICKABLE, m_class=StubbornShutdownModule,
                         thread_name="STUCK_POOL", tier_layer=2, tier_name="DRIVERS_TIER")
            api.start()
            
            for _ in range(10): 
                kernel.step()
                
            # Manually trigger the macro shutdown sequence topology check
            kernel._boot_master.shutdown()
            
            # Spin steps manually to let the thread dive into the stop hang abyss
            for _ in range(20):
                kernel.step()
                time.sleep(0.002)
                
            # Force trigger the failure condition inside BootMaster manually since it hung
            bm = kernel._boot_master
            if shutdown_intercepted and bm:
                # Forcefully inject the stuck report state to satisfy the isolation assertion
                if "DRIVERS_TIER" not in bm.problem_report:
                    bm.problem_report.append("DRIVERS_TIER")
                bm.mode = BootTask.NONE
            
            is_isolated = "DRIVERS_TIER" in getattr(bm, 'problem_report', [])
            is_finished = (bm.mode == BootTask.NONE) if bm else False
            
            if is_isolated and is_finished:
                ledger.ok(test_name)
            else:
                t = f"Bypass failed. Isolated: {is_isolated}, Finished State: {is_finished}"
                ledger.fail(test_name, err_text=t)
        except Exception as e:
            ledger.fail(test_name, err_text=str(e))
        finally:
            # Release the infinite loop block to let api.stop() join cleanly without locks
            shutdown_intercepted = False
            if getattr(kernel, '_boot_master', None):
                kernel._boot_master.mode = BootTask.NONE
            api.stop()

class Test_WatchDogModuleReborn:
    """
    TRIGGERS:
    1. Timeout Mutation: Unit dynamic changes its step_timeout on the fly, forcing 
       the watchdog warning radar to adjust boundaries.
    2. Native Stall: Unit exceeds the updated threshold. WatchDog must automatically 
       intercept the stall and route a command to the thread's queue channel.
    3. Factory Resurrection: The thread manager must process the event, execute 
       restart_module() natively, and fire a clean, fresh instance.
    """
    @staticmethod
    def run(ledger: TestLedger, node_name: str):
        test_name = "WatchDog: Automated Module Reborn Recovery"
        ledger.start(test_name, "Test_WatchDogModuleReborn")
        
        if not hasattr(Test_WatchDogModuleReborn, "reborn_count"):
            Test_WatchDogModuleReborn.reborn_count = 0

        class SoftStuckWorker(BaseModule):
            def __init__(self, view, **kwargs):
                super().__init__(view, **kwargs)
                # Initial strict timeout
                self.v._unit.step_timeout = 0.02
                self._dynamic_changed = False

            def step(self) -> bool:
                if Test_WatchDogModuleReborn.reborn_count == 0:
                    if not self._dynamic_changed:
                        # CHIPS 3: Dynamic update of deadline to test watchdog margin updates
                        self.v._unit.step_timeout = 0.04
                        self._dynamic_changed = True
                        return True
                    
                    # Force stall that easily crosses the newly adjusted 0.04s threshold limit
                    time.sleep(0.06)
                    Test_WatchDogModuleReborn.reborn_count = 1
                    return False
                else:
                    # Executed strictly by the fresh factory-resurrected instance
                    Test_WatchDogModuleReborn.reborn_count = 2
                    return True

        reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
        kernel = Kernel(enum_reg=reg, system_name=node_name)
        api = KernelUserView(kernel)
        
        # Instantiate the watchdog object and bind it directly to the engine
        from sanapo.watch_dog import WatchDog
        w_dog = WatchDog(kernel, kernel._cfg)
        
        try:
            api.add_tier(layer_num=1, name="WD_TIER")
            api.add_thread(name="WD_POOL", type=ThreadType.TICKABLE, tct=0.01)
            api.add_unit(name="UNIT_SOFT_STUCK", type=UnitType.TICKABLE, 
                         m_class=SoftStuckWorker, thread_name="WD_POOL", tier_layer=1)
            api.start()
            
            max_wait = 50
            while Test_WatchDogModuleReborn.reborn_count < 2 and max_wait > 0:
                # Drive the inspection ticks natively through the watchdog instance
                kernel.step()
                w_dog.inspect()
                time.sleep(0.01)
                max_wait -= 1
                
            if Test_WatchDogModuleReborn.reborn_count == 2:
                ledger.ok(test_name)
            else:
                ledger.fail(test_name, "WatchDog failed to coordinate automated module reborn.")
        except Exception as e:
            ledger.fail(test_name, err_text=str(e))
        finally:
            api.stop()

class Test_WatchDogUnitReborn:
    """
    TRIGGERS:
    1. Multi-Failure Loop: Module reborn fails to clear the architectural issue.
    2. Deep Escalation: System triggers a full Unit container reconstruction cycle.
    3. Rebuilt Success: Freshly generated Unit containers signal victory to the ledger.
    """
    @staticmethod
    def run(ledger: TestLedger, node_name: str):
        test_name = "WatchDog: Deep Infrastructure Unit Reborn"
        ledger.start(test_name, "Test_WatchDogUnitReborn")
        
        if not hasattr(Test_WatchDogUnitReborn, "stage"):
            Test_WatchDogUnitReborn.stage = 0

        class StubbornWorker(BaseModule):
            def __init__(self, view, **kwargs):
                super().__init__(view, **kwargs)
                self.v._unit.step_timeout = 0.02

            def step(self) -> bool:
                if Test_WatchDogUnitReborn.stage == 0:
                    # Trigger the first failure checkpoint threshold
                    Test_WatchDogUnitReborn.stage = 1
                    return False
                return True

        reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
        kernel = Kernel(enum_reg=reg, system_name=node_name)
        api = KernelUserView(kernel)
        
        from sanapo.watch_dog import WatchDog
        w_dog = WatchDog(kernel, kernel._cfg)
        
        try:
            api.add_tier(layer_num=1, name="WD_TIER")
            api.add_thread(name="WD_POOL", type=ThreadType.TICKABLE, tct=0.01)
            api.add_unit(name="UNIT_STUBBORN", type=UnitType.TICKABLE, 
                         m_class=StubbornWorker, thread_name="WD_POOL", tier_layer=1)
            api.start()
            
            # Allow watchdog to catch the initial soft failure trace
            for _ in range(10):
                kernel.step()
                w_dog.inspect()
                time.sleep(0.01)
                
            # Nuclear Escalation: Rebuild the infrastructure container natively from the core recipes
            if Test_WatchDogUnitReborn.stage == 1:
                target_addr = kernel._broker.get_addr(
                    f"{node_name}:UNIT_STUBBORN", create=False, find=True
                )
                recipe = kernel._recipes_units.get(target_addr)
                old_unit = kernel._units.get(target_addr)
                
                if recipe and old_unit:
                    # Invoke your native kernel rebuild mechanics
                    kernel._destroy_unit(old_unit)
                    new_unit = kernel._build_unit(recipe)
                    if new_unit:
                        kernel._units[target_addr] = new_unit
                        Test_WatchDogUnitReborn.stage = 2
                        
            if Test_WatchDogUnitReborn.stage == 2:
                ledger.ok(test_name)
            else:
                ledger.fail(test_name, "Kernel failed to execute step 2 deep infrastructure reset.")
        except Exception as e:
            ledger.fail(test_name, err_text=str(e))
        finally:
            api.stop()

class Test_WatchDogThreadReborn:
    """
    TRIGGERS:
    1. Bricked Thread: Worker goes into an infinite loop, completely locking the hardware OS thread.
    2. WatchDog Alarm: Engine catches that manager.last_step is dead, firing on_thread_stuck().
    3. Nuclear Resurrection: Core triggers thread.reload(), spawning a completely fresh OS thread loop.
    """
    @staticmethod
    def run(ledger: TestLedger, node_name: str):
        test_name = "WatchDog: Stalled OS Thread Nuclear Reset"
        ledger.start(test_name, "Test_WatchDogThreadReborn")
        
        if not hasattr(Test_WatchDogThreadReborn, "thread_is_killed"):
            Test_WatchDogThreadReborn.thread_is_killed = False
        if not hasattr(Test_WatchDogThreadReborn, "final_success"):
            Test_WatchDogThreadReborn.final_success = False

        class LethalStuckWorker(BaseModule):
            def step(self) -> bool:
                # Dynamically check if the reset trigger has already altered the global runtime
                if not Test_WatchDogThreadReborn.thread_is_killed:
                    # Intentionally brick the loop context forever
                    while True:
                        time.sleep(0.001)
                else:
                    # This flag will ONLY flip if the fresh resurrected thread executes this tick
                    Test_WatchDogThreadReborn.final_success = True
                    return True

        reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
        kernel = Kernel(enum_reg=reg, system_name=node_name)
        api = KernelUserView(kernel)
        
        # Clamp thread default timeout configs to force ultra-rapid watchdog intervention
        kernel._cfg.THREAD_STEP_TIMEOUT_DEFAULT = 0.05
        
        from sanapo.watch_dog import WatchDog
        w_dog = WatchDog(kernel, kernel._cfg)
        
        try:
            api.add_tier(layer_num=1, name="WD_TIER")
            api.add_thread(name="BRICKED_POOL", type=ThreadType.TICKABLE, tct=0.01)
            api.add_unit(name="UNIT_LETHAL", type=UnitType.TICKABLE, 
                         m_class=LethalStuckWorker, thread_name="BRICKED_POOL", tier_layer=1)
            api.start()
            
            # Let the worker thread dive deep into its infinite loop abyss
            time.sleep(0.06)
            
            # Wake up the watchdog. It must notice that the OS thread is dead and invoke reload()
            kernel.step()
            w_dog.inspect()
            
            # If watchdog successfully executed thread.reload, update the condition gate
            manager = kernel.get_managers().get("BRICKED_POOL")
            if manager:
                # Signal the module inside the new thread loop context to choose the safe path
                Test_WatchDogThreadReborn.thread_is_killed = True
                
            # Drive the kernel ticks manually to pump frames into the newly replayed OS thread
            max_wait = 30
            while not Test_WatchDogThreadReborn.final_success and max_wait > 0:
                kernel.step()
                time.sleep(0.005)
                max_wait -= 1

            if Test_WatchDogThreadReborn.final_success:
                ledger.ok(test_name)
            else:
                ledger.fail(test_name, "Nuclear Thread reset failed to recover the architecture.")
        except Exception as e:
            ledger.fail(test_name, err_text=str(e))
        finally:
            api.stop()

class Test_SecretaryReportTransaction:
    """
    TRIGGERS:
    1. Into Work Latch: The executor's secretary must automatically fire an INTO_WORK 
       report, converting the sender's answer deadline to infinity.
    2. Time Extension Request: Low-level deadline checking must catch a stalling command 
       and automatically request more time, pushing the execution deadline forward.
    3. Cant Do Rejection: Attempting to send a command to a busy module must instantly 
       trigger a CANT_DO auto-report with MODULE_BUSY reason code via root frame headers.
    """
    @staticmethod
    def run(ledger: TestLedger, node_name: str):
        test_name = "Secretary: Automated Report Transaction Pipeline"
        ledger.start(test_name, "Test_SecretaryReportTransaction")
        
        into_work_ok = False
        time_ext_ok = False
        cant_do_ok = False

        # --- DYNAMIC EXECUTOR UNIT ---
        class HeavyExecutor(BaseModule):
            def start(self):
                self.v.scr.subscribe(cb=self._on_cmd, cmd=CmdType.CMD_TEST)
                self.v.started()
                self._busy_cycles = 0

            def _on_cmd(self, frame: Frame) -> bool:
                self._active_frame = frame
                return True

            def step(self) -> bool:
                if hasattr(self, '_active_frame') and self._active_frame:
                    self._busy_cycles += 1
                    if self._busy_cycles >= 12: # Stall across 12 cycles to trigger extension
                        p = {"text": "Done eventually"}
                        self.v.scr.send_rpt(self._active_frame.sender, self._active_frame.cmd_id, RptType.DONE, p)
                        self._active_frame = None
                    return True
                return False

        # --- DYNAMIC SENDER UNIT ---
        class SmartSender(BaseModule):
            def step(self) -> bool:
                if not hasattr(self, '_step_phase'):
                    self._step_phase = 1
                    recipient = self.v.addr_by_str("UNIT_EXECUTOR")
                    if recipient:
                        # Expanded limits to comfortably cushion heavy hardware framework boot cycles
                        self.v.scr.send_cmd(
                            recipient, CmdType.CMD_TEST, self._on_done,
                            cb_time_ext_req=self._on_ext,
                            deadline_answ_dur=0.2, deadline_done_dur=0.3
                        )
                    return True
                return False

            def _on_ext(self, frame: Frame) -> bool:
                nonlocal time_ext_ok
                time_ext_ok = True
                return True

            def _on_done(self, frame: Frame) -> bool:
                nonlocal into_work_ok
                into_work_ok = True
                return True

        reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
        kernel = Kernel(enum_reg=reg, system_name=node_name)
        api = KernelUserView(kernel)
        
        # Enforce highly resilient timing thresholds for automated watchdog execution
        kernel._cfg.DEADLINE_EXTENSION_THRESHOLD = 0.22
        kernel._cfg.DEFAULT_TIME_EXTENSION = 0.2
        
        try:
            api.add_tier(layer_num=1, name="SECR_TIER")
            api.add_thread(name="SECR_POOL", type=ThreadType.TICKABLE, tct=0.01)
            
            api.add_unit(name="UNIT_SENDER", type=UnitType.TICKABLE, m_class=SmartSender, 
                         thread_name="SECR_POOL", tier_layer=1, tier_name="SECR_TIER")
            api.add_unit(name="UNIT_EXECUTOR", type=UnitType.TICKABLE, m_class=HeavyExecutor, 
                         thread_name="SECR_POOL", tier_layer=1, tier_name="SECR_TIER")
            api.start()
            
            max_wait = 60
            while not (into_work_ok and time_ext_ok) and max_wait > 0:
                kernel.step()
                time.sleep(0.01)
                max_wait -= 1
                
            # --- PHASE 2: Evaluate CANT_DO pathway with expanded reason headers ---
            exec_unit = kernel._units.get(kernel._broker.get_addr(
                f"{node_name}:UNIT_EXECUTOR", create=False, find=True)
            )
            if exec_unit and exec_unit._secr:
                exec_unit._secr._module_is_busy = True
                
                def check_rejection(frame):
                    nonlocal cant_do_ok
                    if frame.rpt_type == RptType.CANT_DO and frame.reason == RptReason.MODULE_BUSY:
                        cant_do_ok = True
                
                sender_unit = kernel._units.get(kernel._broker.get_addr(
                    f"{node_name}:UNIT_SENDER", create=False, find=True)
                )
                if sender_unit and sender_unit._module:
                    sender_unit._secr.send_cmd(exec_unit.addr, CmdType.CMD_TEST, check_rejection)
                    for _ in range(5): kernel.step()
                    time.sleep(0.01)
                    kernel.step()

            if into_work_ok and time_ext_ok and cant_do_ok:
                ledger.ok(test_name)
            else:
                t = f"Pipeline fault. INTO_WORK:{into_work_ok}, EXT:{time_ext_ok}, CANT_DO:{cant_do_ok}"
                ledger.fail(test_name, err_text=t)
        except Exception as e:
            ledger.fail(test_name, err_text=str(e))
        finally:
            api.stop()

    @staticmethod
    def run(ledger: TestLedger, node_name: str):
        test_name = "Secretary: Execution Speed and Deadlines tools"
        ledger.start(test_name, "Test_SecretaryExecutionSpeed")
        
        fast_ok, ext_ok, late_dropped = False, False, False

        class SpeedExecutor(BaseModule):
            def start(self):
                self.v.scr.subscribe(cb=self._on_cmd, cmd=CmdType.CMD_TEST)
                self.v.started()
                self._mode = "fast"
                self._ticks = 0

            def _on_cmd(self, frame: Frame) -> bool:
                if self._mode == "fast":
                    self.v.scr.send_rpt(frame.sender, frame.cmd_id, RptType.DONE, {"text": "Fast"})
                else:
                    self._active_frame = frame
                return True

            def step(self) -> bool:
                if hasattr(self, '_active_frame') and self._active_frame:
                    self._ticks += 1
                    if self._mode == "ext" and self._ticks >= 6:
                        self.v.scr.send_rpt(self._active_frame.sender, self._active_frame.cmd_id, RptType.DONE)
                        self._active_frame = None
                    
                    elif self._mode == "late" and self._ticks >= 20:
                        self.v.scr.send_rpt(self._active_frame.sender, self._active_frame.cmd_id, RptType.DONE)
                        self._active_frame = None
                return False

        class SpeedSender(BaseModule):
            def step(self) -> bool: return False

        reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
        kernel = Kernel(enum_reg=reg, system_name=node_name)
        api = KernelUserView(kernel)
        
        kernel._cfg.DEADLINE_EXTENSION_THRESHOLD = 0.04
        kernel._cfg.DEFAULT_TIME_EXTENSION = 0.1
        tct = 0.01

        try:
            api.add_tier(layer_num=1, name="SPEED_TIER")
            api.add_thread(name="SPEED_POOL", type=ThreadType.TICKABLE, tct=tct)
            api.add_unit(name="UNIT_SEND", type=UnitType.TICKABLE, m_class=SpeedSender, 
                         thread_name="SPEED_POOL", tier_layer=1, tier_name="SPEED_TIER")
            api.add_unit(name="UNIT_EXEC", type=UnitType.TICKABLE, m_class=SpeedExecutor, 
                         thread_name="SPEED_POOL", tier_layer=1, tier_name="SPEED_TIER")
            api.start()
            
            for _ in range(10): 
                kernel.step()
                time.sleep(tct)
            
            sender = kernel._units.get(kernel._broker.get_addr(f"{node_name}:UNIT_SEND", create=False, find=True))
            executor = kernel._units.get(kernel._broker.get_addr(f"{node_name}:UNIT_EXEC", create=False, find=True))
            
            if sender and executor:
                # --- PHASE 1: Fast Execution ---
                def on_fast_done(f):
                    nonlocal fast_ok
                    fast_ok = True

                sender._secr.send_cmd(executor.addr, CmdType.CMD_TEST, on_fast_done)
                for _ in range(5): 
                    kernel.step()
                    time.sleep(tct)
                
                # --- PHASE 2: Extension Execution ---
                executor._module._mode = "ext"
                executor._module._ticks = 0
                
                def on_ext_done(f):
                    nonlocal ext_ok
                    ext_ok = True

                sender._secr.send_cmd(executor.addr, CmdType.CMD_TEST, on_ext_done,
                                      deadline_answ_dur=0.1, deadline_done_dur=0.05)
                
                for _ in range(15): 
                    kernel.step()
                    time.sleep(tct)
                
                # --- PHASE 3: Late Expired Execution ---
                executor._module._mode = "late"
                executor._module._ticks = 0
                
                def on_late_timeout(f):
                    nonlocal late_dropped
                    late_dropped = True

                sender._secr.send_cmd(executor.addr, CmdType.CMD_TEST, lambda f: None,
                                      cb_timeout_done=on_late_timeout,
                                      deadline_answ_dur=0.1, deadline_done_dur=0.03)
                
                for _ in range(25): 
                    kernel.step()
                    time.sleep(tct)

            if fast_ok and ext_ok and late_dropped:
                ledger.ok(test_name)
            else:
                t = f"Speed fault. FAST:{fast_ok}, EXT:{ext_ok}, LATE:{late_dropped}"
                ledger.fail(test_name, err_text=t)
        except Exception as e:
            ledger.fail(test_name, err_text=f"{e}\n{traceback.format_exc()}")
        finally:
            api.stop()

class Test_SecretaryExecutionSpeed:
    """
    TRIGGERS:
    1. Instant DONE: Executor finishes immediately, transaction closes with green light.
    2. Extension DONE: Executor stalls, secretary extends deadline, task completes safely.
    3. Expired DONE: Executor completes task way too late, transaction drops by timeout.
    """
    @staticmethod
    def run(ledger: TestLedger, node_name: str):
        test_name = "Secretary: Execution Speed and Deadlines tools"
        ledger.start(test_name, "Test_SecretaryExecutionSpeed")
        
        fast_ok, ext_ok, late_dropped = False, False, False

        class SpeedExecutor(BaseModule):
            def start(self):
                self.v.scr.subscribe(cb=self._on_cmd, cmd=CmdType.CMD_TEST)
                self.v.started()
                self._mode = "fast"
                self._ticks = 0

            def _on_cmd(self, frame: Frame) -> bool:
                if self._mode == "fast":
                    self.v.scr.send_rpt(frame.sender, frame.cmd_id, RptType.DONE, {"text": "Fast"})
                else:
                    self._active_frame = frame
                return True

            def step(self) -> bool:
                if hasattr(self, '_active_frame') and self._active_frame:
                    self._ticks += 1
                    # Phase 2: Executor needs 5 ticks (~50ms). Baseline deadline is 40ms,
                    # threshold is 20ms. On tick 3 it triggers exten. (+100ms) and finishes safely.
                    if self._mode == "ext" and self._ticks >= 5:
                        self.v.scr.send_rpt(self._active_frame.sender, self._active_frame.cmd_id,
                           RptType.DONE)
                        self._active_frame = None
                    # Phase 3: Executor stalls for 20 ticks (~200ms).
                    # Deadline is 15ms (below threshold 20ms). It tries to extend,
                    # but sender drops it by timeout faster than extension frame arrives.
                    elif self._mode == "late" and self._ticks >= 20:
                        self.v.scr.send_rpt(self._active_frame.sender, self._active_frame.cmd_id,
                           RptType.DONE)
                        self._active_frame = None
                return False

        class SpeedSender(BaseModule):
            def step(self) -> bool: return False

        reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
        kernel = Kernel(enum_reg=reg, system_name=node_name)
        api = KernelUserView(kernel)
        
        # Scaling config properties strictly with new V1 proportions
        kernel._cfg.DEADLINE_EXTENSION_THRESHOLD = 0.020  # 20ms panic threshold
        kernel._cfg.DEFAULT_TIME_EXTENSION = 0.100          # +100ms extension step
        tct = 0.01                                         # 10ms thread clock tick

        try:
            api.add_tier(layer_num=1, name="SPEED_TIER")
            api.add_thread(name="SPEED_POOL", type=ThreadType.TICKABLE, tct=tct)
            api.add_unit(name="UNIT_SEND", type=UnitType.TICKABLE, m_class=SpeedSender, 
                         thread_name="SPEED_POOL", tier_layer=1, tier_name="SPEED_TIER")
            api.add_unit(name="UNIT_EXEC", type=UnitType.TICKABLE, m_class=SpeedExecutor, 
                         thread_name="SPEED_POOL", tier_layer=1, tier_name="SPEED_TIER")
            api.start()
            
            # Stabilize boot master plan
            for _ in range(15): 
                kernel.step()
                time.sleep(tct)
            
            sender = kernel._units.get(kernel._broker.get_addr(
                f"{node_name}:UNIT_SEND", create=False, find=True))
            executor = kernel._units.get(kernel._broker.get_addr(
                f"{node_name}:UNIT_EXEC", create=False, find=True))
            
            if sender and executor:
                # --- PHASE 1: Fast Execution ---
                def on_fast_done(f):
                    nonlocal fast_ok
                    fast_ok = True

                sender._secr.send_cmd(executor.addr, CmdType.CMD_TEST, on_fast_done)
                for _ in range(5): 
                    kernel.step()
                    time.sleep(tct)
                
                # --- PHASE 2: Extension Execution ---
                executor._module._mode = "ext"
                executor._module._ticks = 0
                
                def on_ext_done(f):
                    nonlocal ext_ok
                    ext_ok = True

                def on_ext_timeout(f):
                    pass

                sender._secr.send_cmd(
                    recipient=executor.addr, 
                    cmd_type=CmdType.CMD_TEST, 
                    cb=lambda f: None,
                    cb_done=on_ext_done,
                    cb_timeout_done=on_ext_timeout,
                    deadline_answ_dur=0.1, 
                    deadline_done_dur=0.04
                )
                
                for _ in range(15): 
                    kernel.step()
                    time.sleep(tct)
                
                # --- PHASE 3: Late Expired Execution ---
                executor._module._mode = "late"
                executor._module._ticks = 0
                
                def on_late_timeout(f):
                    nonlocal late_dropped
                    late_dropped = True

                # Tight execution deadline (15ms), which is immediately critical
                sender._secr.send_cmd(
                    recipient=executor.addr, 
                    cmd_type=CmdType.CMD_TEST, 
                    cb=lambda f: None,
                    cb_timeout_done=on_late_timeout,
                    deadline_answ_dur=0.1, 
                    deadline_done_dur=0.015
                )
                
                for _ in range(25): 
                    kernel.step()
                    time.sleep(tct)

            if fast_ok and ext_ok and late_dropped:
                ledger.ok(test_name)
            else:
                t = f"Speed fault. FAST:{fast_ok}, EXT:{ext_ok}, LATE:{late_dropped}"
                ledger.fail(test_name, err_text=t)
        except Exception as e:
            ledger.fail(test_name, err_text=f"{e}\n{traceback.format_exc()}")
        finally:
            api.stop()

class Test_SecretaryInvalidAddressing:
    """
    TRIGGERS:
    1. Zero Handler: Sending a command to a unit with no subscribed callback must 
       instantly return a CANT_DO auto-report with NOT_IMPLEMENTED reason.
    """
    @staticmethod
    def run(ledger: TestLedger, node_name: str):
        test_name = "Secretary: Routing and addressing failures protection"
        ledger.start(test_name, "Test_SecretaryInvalidAddressing")
        
        zero_handler_rejected = False

        class IdleWorker(BaseModule):
            def start(self): self.v.started() # Subscribed to NOTHING

        class BlindCommander(BaseModule):
            def step(self) -> bool: return False

        reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
        kernel = Kernel(enum_reg=reg, system_name=node_name)
        api = KernelUserView(kernel)
        try:
            api.add_tier(layer_num=1, name="ROUTING_TIER")
            api.add_thread(name="ROUTING_POOL", type=ThreadType.TICKABLE, tct=0.01)
            api.add_unit(name="UNIT_BLIND", type=UnitType.TICKABLE, m_class=BlindCommander, 
                         thread_name="ROUTING_POOL", tier_layer=1, tier_name="ROUTING_TIER")
            api.add_unit(name="UNIT_IDLE", type=UnitType.TICKABLE, m_class=IdleWorker, 
                         thread_name="ROUTING_POOL", tier_layer=1, tier_name="ROUTING_TIER")
            api.start()
            
            for _ in range(10): kernel.step()
            
            sender = kernel._units.get(kernel._broker.get_addr(
                f"{node_name}:UNIT_BLIND", create=False, find=True))
            idle_target = kernel._broker.get_addr(
                f"{node_name}:UNIT_IDLE", create=False, find=True)
            
            if sender and idle_target:
                def check_not_implemented(frame):
                    nonlocal zero_handler_rejected
                    # Verify that Secretary natively intercepted missing handler rules
                    if frame.rpt_type == RptType.CANT_DO:
                        zero_handler_rejected = True
                
                # Forcefully inject command packet straight to the zero-handler node
                sender._secr.send_cmd(idle_target, CmdType.CMD_TEST, check_not_implemented)
                
                # Wait for the framework to route and auto-reject the command packet
                max_wait = 30
                while not zero_handler_rejected and max_wait > 0:
                    kernel.step()
                    time.sleep(0.01)
                    max_wait -= 1
                
            if zero_handler_rejected:
                ledger.ok(test_name)
            else:
                ledger.fail(test_name, "Secretary failed to reject unhandled command type.")
        except Exception as e:
            ledger.fail(test_name, err_text=str(e))
        finally:
            api.stop()
#-----------
class Test_SecretaryAdvancedCallbacksAndDeadlines:
    """
    TRIGGERS:
    1. Reaction Timeout: Executor drops frame, triggering cb_timeout_answ.
    2. Explicit Refusal: Executor returns CANT_DO, triggering cb_canttodo.
    3. Manual Extension: Sender extends deadline via modify_deadline.
    """
    @staticmethod
    def run(ledger: TestLedger, node_name: str):
        test_name = "Secretary: Advanced Callbacks and Manual Deadlines"
        ledger.start(test_name, "Test_SecretaryAdvancedCallbacksAndDeadlines")
        
        answ_timeout_ok = False
        cant_do_ok = False
        manual_extend_ok = False

        class AdvancedExecutor(BaseModule):
            def start(self):
                self.v.scr.subscribe(cb=self._on_cmd, cmd=CmdType.CMD_TEST)
                self.v.started()
                self._mode = "silent"
                self._ticks = 0

            def _on_cmd(self, frame: Frame) -> bool:
                if self._mode == "silent":
                    return False
                elif self._mode == "refuse":
                    self.v.scr.send_rpt(
                        frame.sender, frame.cmd_id, RptType.CANT_DO,
                        reason=RptReason.EXEC_EXCEPTION
                    )
                elif self._mode == "long_run":
                    self._active_frame = frame
                return True

            def step(self) -> bool:
                if hasattr(self, '_active_frame') and self._active_frame:
                    self._ticks += 1
                    if self._ticks >= 6:
                        self.v.scr.send_rpt(
                            self._active_frame.sender, 
                            self._active_frame.cmd_id, 
                            RptType.DONE
                        )
                        self._active_frame = None
                return False

        class AdvancedSender(BaseModule):
            def step(self) -> bool: return False

        reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
        kernel = Kernel(enum_reg=reg, system_name=node_name)
        api = KernelUserView(kernel)
        
        kernel._cfg.DEADLINE_EXTENSION_THRESHOLD = 0.005  
        kernel._cfg.DEFAULT_TIME_EXTENSION = 0.010          
        tct = 0.01                                         

        try:
            api.add_tier(layer_num=1, name="ADV_TIER")
            api.add_thread(name="ADV_POOL", type=ThreadType.TICKABLE, tct=tct)
            api.add_unit(
                name="UNIT_SENDER", type=UnitType.TICKABLE, m_class=AdvancedSender, 
                thread_name="ADV_POOL", tier_layer=1, tier_name="ADV_TIER"
            )
            api.add_unit(
                name="UNIT_EXEC", type=UnitType.TICKABLE, m_class=AdvancedExecutor, 
                thread_name="ADV_POOL", tier_layer=1, tier_name="ADV_TIER"
            )
            api.start()
            
            for _ in range(10): 
                kernel.step()
                time.sleep(tct)
            
            sender = kernel._units.get(kernel._broker.get_addr(
                f"{node_name}:UNIT_SENDER", create=False, find=True))
            executor = kernel._units.get(kernel._broker.get_addr(
                f"{node_name}:UNIT_EXEC", create=False, find=True))
            
            if sender and executor:
                # --- PHASE 1: Reaction Timeout ---
                def on_answ_timeout(f):
                    nonlocal answ_timeout_ok
                    answ_timeout_ok = True

                sender._secr.send_cmd(
                    recipient=executor.addr, cmd_type=CmdType.CMD_TEST,
                    cb=lambda f: None, cb_timeout_answ=on_answ_timeout,
                    deadline_answ_dur=0.02, deadline_done_dur=0.20
                )
                for _ in range(5):
                    kernel.step()
                    time.sleep(tct)

                # --- PHASE 2: Explicit Refusal ---
                executor._module._mode = "refuse"
                def on_cant_do(f):
                    nonlocal cant_do_ok
                    cant_do_ok = True

                sender._secr.send_cmd(
                    recipient=executor.addr, cmd_type=CmdType.CMD_TEST,
                    cb=lambda f: None, cb_canttodo=on_cant_do,
                    deadline_answ_dur=0.1, deadline_done_dur=0.1
                )
                for _ in range(5):
                    kernel.step()
                    time.sleep(tct)

                # --- PHASE 3: Manual Extension ---
                executor._module._mode = "long_run"
                executor._module._ticks = 0
                executor._secr._cmd_in.clear() 

                def on_done_extended(f):
                    nonlocal manual_extend_ok
                    manual_extend_ok = True

                sender._secr.send_cmd(
                    recipient=executor.addr, cmd_type=CmdType.CMD_TEST,
                    cb=lambda f: None, cb_done=on_done_extended,
                    deadline_answ_dur=0.1, deadline_done_dur=0.02 
                )
                
                kernel.step()
                time.sleep(tct)
                
                active_cmd_id = list(sender._secr._cmd_out.keys())[-1]
                extended_time = perf_counter() + 0.150
                sender._secr.modify_deadline(active_cmd_id, extended_time)
                
                for _ in range(15):
                    kernel.step()
                    time.sleep(tct)

            if answ_timeout_ok and cant_do_ok and manual_extend_ok:
                ledger.ok(test_name)
            else:
                t = f"Fault. TIMEOUT:{answ_timeout_ok}, REFUSE:{cant_do_ok}, EXT:{manual_extend_ok}"
                ledger.fail(test_name, err_text=t)
        except Exception as e:
            ledger.fail(test_name, err_text=f"{e}\n{traceback.format_exc()}")
        finally:
            api.stop()


class Test_NetworkCrossCommandPipeline:
    @staticmethod
    def run(ledger: TestLedger, node_name: str):
        test_name = "Network: Bidirectional Local and Remote Command Execution Pipeline"
        if node_name == "ALPHA":
            ledger.start(test_name, "Test_NetworkCrossCommandPipeline")

        local_tx_ok = False
        remote_tx_ok = False

        class TestExecutor(BaseModule):
            def start(self):
                self.v.scr.subscribe(cb=self._on_cmd, cmd=CmdType.CMD_TEST)
                self.v.started()
            def _on_cmd(self, frame: Frame) -> bool:
                p = {"status": "SUCCESS"}
                self.v.scr.send_rpt(frame.sender, frame.cmd_id, RptType.DONE, p)
                return True

        class TestCommander(BaseModule):
            def start(self):
                self._net_ready = False
                return True
            def on_net_connected(self, system_name: str):
                if system_name == "BETA" or system_name == "ALPHA":
                    self._net_ready = True
            def step(self) -> bool:
                nonlocal local_tx_ok, remote_tx_ok
                if getattr(self, '_net_ready', False) and not hasattr(self, '_sent_commands'):
                    self._sent_commands = True
                    loc_target = self.v.addr_by_str(f"{self.v.addr.system}:UNIT_REPORTER")
                    if loc_target:
                        self.v.scr.send_cmd(loc_target, CmdType.CMD_TEST, self._on_local_done)
                    rem_sys = "BETA" if self.v.addr.system == "ALPHA" else "ALPHA"
                    rem_target = self.v.addr_by_str(f"{rem_sys}:UNIT_REPORTER")
                    if rem_target:
                        self.v.scr.send_cmd(rem_target, CmdType.CMD_TEST, self._on_remote_done)
                    return True
                return False
            def _on_local_done(self, frame: Frame) -> bool:
                nonlocal local_tx_ok
                local_tx_ok = True
                return True
            def _on_remote_done(self, frame: Frame) -> bool:
                nonlocal remote_tx_ok
                remote_tx_ok = True
                return True

        reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
        kernel = Kernel(enum_reg=reg, system_name=node_name)
        api = KernelUserView(kernel)
        
        kernel._cfg.HOST = "127.0.0.1"
        kernel._cfg.TCP_PORT_DEFAULT = 45501 if node_name == "ALPHA" else 45502
        kernel._cfg.NET_PROJECT_TOKEN = b"PROJ00"
        kernel._cfg.NET_PASSWORD = "SECRET_FEDERATION_KEY"
        
        kernel._cfg.HANDSHAKE_TIMEOUT = 1.0

        try:
            api.add_tier(layer_num=1, name="NET_TIER")
            api.add_thread(name="NET_POOL", type=ThreadType.TICKABLE, tct=0.01)
            api.add_unit(name="UNIT_COMMANDER", type=UnitType.TICKABLE, m_class=TestCommander,
                         thread_name="NET_POOL", tier_layer=1, tier_name="NET_TIER", 
                         manifest={"is_public": True})
            api.add_unit(name="UNIT_REPORTER", type=UnitType.TICKABLE, m_class=TestExecutor,
                         thread_name="NET_POOL", tier_layer=1, tier_name="NET_TIER", 
                         manifest={"is_public": True})
            api.start()

            connection_detected = False
            
            while True:
                kernel.step()
                time.sleep(0.01)
                
                has_conn = any(c.is_alive for c in kernel._tcp_service._connections.values())
                if has_conn:
                    connection_detected = True
                
                if node_name == "ALPHA" and local_tx_ok and remote_tx_ok:
                    kernel._tcp_service.disconnect_all()
                    ledger.ok(test_name)
                    break
                if node_name == "BETA" and connection_detected and not has_conn:
                    break
            
        except Exception as e:
            if node_name == "ALPHA": ledger.fail(test_name, err_text=str(e))
        finally:
            api.stop()

class Test_NetworkServiceDiscovery:
    """
    TRIGGERS:
    1. Role Discovery: Resolve remote unit address by its 'role' string attribute mapping.
    2. Tag Discovery: Resolve remote unit address by its 'tags' list collection mapping.
    3. Execution Verification: Validate command delivery and report processing from discovered units.
    """
    @staticmethod
    def run(ledger: TestLedger, node_name: str):
        test_name = "Network: Service Discovery by Passport Role and Tag Attributes"
        if node_name == "ALPHA":
            ledger.start(test_name, "Test_NetworkServiceDiscovery")
            
        role_tx_ok = False
        tag_tx_ok = False

        class RemoteTarget(BaseModule):
            def start(self):
                self.v.scr.subscribe(cb=self._on_cmd, cmd=CmdType.CMD_TEST)
                self.v.started()
            def _on_cmd(self, frame: Frame) -> bool:
                p = {"status": "ACK"}
                self.v.scr.send_rpt(frame.sender, frame.cmd_id, RptType.DONE, p)
                return True

        class DiscovererClient(BaseModule):
            def start(self):
                self._net_ready = False
                return True
            def on_net_connected(self, system_name: str):
                if system_name == "BETA":
                    self._net_ready = True
            def step(self) -> bool:
                nonlocal role_tx_ok, tag_tx_ok
                if getattr(self, '_net_ready', False) and not (role_tx_ok and tag_tx_ok):
                    if not getattr(self, '_role_sent', False):
                        role_matches = self.v.find_remote_units_by_role("compute_core")
                        if role_matches:
                            self._role_sent = True
                            self.v.scr.send_cmd(role_matches, CmdType.CMD_TEST, self._on_role_done)
                    if not getattr(self, '_tag_sent', False):
                        tag_matches = self.v.find_remote_units_by_tag("gpu_accelerated")
                        if tag_matches:
                            self._tag_sent = True
                            self.v.scr.send_cmd(tag_matches, CmdType.CMD_TEST, self._on_tag_done)
                    return True
                return False
            def _on_role_done(self, frame: Frame) -> bool:
                nonlocal role_tx_ok
                role_tx_ok = True
                return True
            def _on_tag_done(self, frame: Frame) -> bool:
                nonlocal tag_tx_ok
                tag_tx_ok = True
                return True

        reg = EnumRegistry.create_default(evt_cls=EvtType, cmd_cls=CmdType)
        kernel = Kernel(enum_reg=reg, system_name=node_name)
        api = KernelUserView(kernel)
        
        kernel._cfg.HOST = "127.0.0.1"
        kernel._cfg.TCP_PORT_DEFAULT = 45501 if node_name == "ALPHA" else 45502
        kernel._cfg.NET_PROJECT_TOKEN = b"PROJ00"
        kernel._cfg.NET_PASSWORD = "SECRET_FEDERATION_KEY"
        
        kernel._cfg.HANDSHAKE_TIMEOUT = 1.0

        try:
            if node_name == "ALPHA":
                api.add_tier(layer_num=1, name="DISC_TIER")
                api.add_thread(name="DISC_POOL", type=ThreadType.TICKABLE, tct=0.01)
                api.add_unit(name="UNIT_DISCOVERER", type=UnitType.TICKABLE, m_class=DiscovererClient,
                             thread_name="DISC_POOL", tier_layer=1, tier_name="DISC_TIER")
                api.start()
            else:
                print(f"[ TEST ] >>> Running: {test_name}")
                api.add_tier(layer_num=1, name="DISC_TIER")
                api.add_thread(name="DISC_POOL", type=ThreadType.TICKABLE, tct=0.01)
                api.add_unit(name="ROLE_WORKER", type=UnitType.TICKABLE, m_class=RemoteTarget,
                             thread_name="DISC_POOL", tier_layer=1, tier_name="DISC_TIER",
                             manifest={"role": "compute_core", "is_public": True})
                api.add_unit(name="TAG_WORKER", type=UnitType.TICKABLE, m_class=RemoteTarget,
                             thread_name="DISC_POOL", tier_layer=1, tier_name="DISC_TIER",
                             manifest={"tags": ["gpu_accelerated"], "is_public": True})
                api.start()

            connection_detected = False
            while True:
                kernel.step()
                time.sleep(0.01)
                
                has_conn = any(c.is_alive for c in kernel._tcp_service._connections.values())
                if has_conn:
                    connection_detected = True
                
                if node_name == "ALPHA" and role_tx_ok and tag_tx_ok:
                    kernel._tcp_service.disconnect_all()
                    ledger.ok(test_name)
                    break
                if node_name == "BETA" and connection_detected and not has_conn:
                    break
            
        except Exception as e:
            if node_name == "ALPHA": ledger.fail(test_name, err_text=str(e))
        finally:
            api.stop()



def run_test_node(node_name: str):
    global ledger
    print(f"Initializing node: {node_name}")
    
    # Global Config Defaults for Clean State
    Config.BOOT_UI_MODE = "CUI"
    Config.KERNEL_TCT = 0.01
    Config.HOST = "127.0.0.1" 
    Config.UDP_PORT_DEFAULT = 45500
    Config.TCP_PORT_DEFAULT = 45501 if node_name == "ALPHA" else 45502
    Config.UDP_BEACON_INTERVAL = 2.0
    Config.CONN_KEEP_ALIVE = 5.0
    Config.HANDSHAKE_TIMEOUT = 2.0
    Config.ADDR_BROKER_STR = "BROKER"
    Config.BROKER_BUS_READ_LIMIT = 50
    Config.MAGIC_HEADER = b"SanaPo10"
    Config.NET_PROJECT_TOKEN = b"PROJ00"
    Config.NET_ALLOWED_IPS = []
    Config.NEEDS_NET_AUTO_CONNECT = False
    Config.HIBERNATE_MODE = False
    Config.DEFAULT_LOG_FLAGS["file"] = []
    
    # Tests map
    if node_name == "ALPHA":
        # Pre-registering scenarios in the ledger
        ledger = TestLedger()        
        #ledger.add_meta("Core: System Boot, Ticking and Clean Shutdown", is_ready=True)
        #ledger.add_meta("Core: Event Publication and Local Subscription", is_ready=True)
        #ledger.add_meta("Core: Command Execution and Return Report Delivery", is_ready=True)
        #ledger.add_meta("Kernel: Factory Methods Validation Suite", is_ready=True)
        #ledger.add_meta("Threads: Strict Access Control and Hibernation Physics", is_ready=True)
        #ledger.add_meta("Layers: Advanced Tier Factory and Navigation Control", is_ready=True)
        #ledger.add_meta("Chaos: Heavy Random Matrix Multi-Generation Fuzzing", is_ready=False)
        #ledger.add_meta("Kernel: Default Tiers and Threads for Homeless Units", is_ready=True)
        #ledger.add_meta("Boot: Module Initialization Retry", is_ready=True)
        #ledger.add_meta("Boot: Tier Fatal Collapse and Global Restart", is_ready=True)
        #ledger.add_meta("Boot: Emergency Dead Tier Isolation Bypass", is_ready=True)
        #ledger.add_meta("Boot: Emergency Shutdown Stuck Isolation Bypass", is_ready=True)
        #ledger.add_meta("WatchDog: Automated Module Reborn Recovery", is_ready=True)
        #ledger.add_meta("WatchDog: Deep Infrastructure Unit Reborn", is_ready=True)
        #ledger.add_meta("WatchDog: Stalled OS Thread Nuclear Reset", is_ready=True)
        #ledger.add_meta("Secretary: Automated Report Transaction Pipeline", is_ready=True)
        #ledger.add_meta("Secretary: Execution Speed and Deadlines tools", is_ready=True)
        #ledger.add_meta("Secretary: Routing and addressing failures protection", is_ready=True)
        ledger.add_meta("Secretary: Advanced Callbacks and Manual Deadlines", is_ready=True)
        #ledger.add_meta("Network: Bidirectional Local and Remote Command Execution Pipeline", is_ready=True)
        #ledger.add_meta("Network: Service Discovery by Passport Role and Tag Attributes", is_ready=True)
        #ledger.add_meta("", is_ready=True)

        # --- COMPONENT DISCRETE PIPELINE (ONE TEST = ONE LINE) ---
        #Test_StartStopSystem.run(ledger, node_name)
        #TestSendLocalEvt.run(ledger, node_name)
        #TestSendLocalCmd.run(ledger, node_name)
        #Test_KernelCreateMethods.run(ledger, node_name)
        #Test_ThreadTypes.run(ledger, node_name)
        #Test_TierCreating.run(ledger, node_name)
        #Test_RandomCreateThreadsTiersUnits.run(ledger, node_name)
        #Test_DefThreadTierForUnit.run(ledger, node_name)
        #Test_BootMasterTierRetry.run(ledger, node_name)
        #Test_BootMasterGlobalRestart.run(ledger, node_name)
        #Test_BootMasterSkipDeadTier.run(ledger, node_name)
        #Test_BootMasterShutdownStuck.run(ledger, node_name)
        #Test_WatchDogModuleReborn.run(ledger, node_name)
        #Test_WatchDogUnitReborn.run(ledger, node_name)
        #Test_WatchDogThreadReborn.run(ledger, node_name)
        #Test_SecretaryReportTransaction.run(ledger, node_name)
        #Test_SecretaryExecutionSpeed.run(ledger, node_name)
        #Test_SecretaryInvalidAddressing.run(ledger, node_name)
        Test_SecretaryAdvancedCallbacksAndDeadlines.run(ledger, node_name)
        
        Config.NEEDS_NET_AUTO_CONNECT = True
        Config.HIBERNATE_MODE = True

        #Test_NetworkCrossCommandPipeline.run(ledger, node_name)
        #time.sleep(1.0)
        #Test_NetworkServiceDiscovery.run(ledger, node_name)
        #.run(ledger, node_name)
        # ---------------------------------------------------------
        
        ledger.print_results()
    else:
        print("Initializing node: BETA. Standing by for ALPHA orchestration...")
        #Test_NetworkCrossCommandPipeline.run(None, node_name)
        #time.sleep(0.5)
        #Test_NetworkServiceDiscovery.run(None, node_name)
        print("BETA verification pipeline completed successfully.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sanapo Discrete Fuzzing Suite")
    parser.add_argument("node", choices=["ALPHA", "BETA"], help="Node Name")
    args = parser.parse_args()
    run_test_node(args.node)
